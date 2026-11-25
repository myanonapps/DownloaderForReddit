# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a personal fork of MalloyDelacroix/DownloaderForReddit (remote `upstream`; the fork is remote `fork`). It has been ported to Python 3.12 and PyQt6, made to work on Linux, and its schema extended with a download *source* (Reddit API vs. archive services). The README says it is "not fully working". The CI workflows in `.github/workflows/` still target Python 3.9 and are stale for this fork.

## Commands

The venv is in `.venv` (Python 3.12). Run everything from the repo root, because `Migrator` resolves `alembic/` relative to the CWD.

- Run app: `python main.py` (VSCode launch config "Downloader for reddit" does the same)
- All tests: `python -m unittest`
- Single test: `python -m unittest Tests.unittests.core.test_download_runner` (or `...TestClass.test_method`)
- Lint: pylint, configured in `.vscode/settings.json` (`--disable=C0114,C0115,C0116 --max-line-length=225 --extension-pkg-whitelist=PyQt6`)
- Regenerate GUI code from Qt Designer files: `python Tools/ui_converter.py <name|list>` (runs `pyuic6`)
- New DB migration: `alembic revision --autogenerate -m "..."`. `alembic/env.py` overrides the dummy URL in `alembic.ini` with the real user database.
- Package: `pyinstaller build_github.spec`

## Architecture

**Startup (`main.py`)**: parse CLI args (`core/cli.py`) → set up logging → `Migrator.check_migration()` (runs alembic `upgrade head` when `version.py`'s `__version__` is newer than the last `Version` row in the DB) → build the Qt app. Two QObjects are moved onto their own QThreads: `MessageReceiver`, which drains the global message queue into GUI signals, and `Scheduler`.

**Service locator**: `utils/injector.py` holds lazily created singletons: `SettingsManager`, `DatabaseHandler`, the message `Queue`, and `Scheduler`. Code gets these through `injector.get_*()` and does not construct them. Tests swap them by assigning `injector.settings_manager` and `injector.database_handler = DatabaseHandler(in_memory=True)`.

**User data** lives in `system_util.get_data_directory()` (`%APPDATA%/SomeGuySoftware/DownloaderForReddit`, `~/.SomeGuySoftware/DownloaderForReddit` on Linux). It contains `config.toml` (read by `persistence/settings_manager.py`, which exposes config keys as attributes) and the SQLite database.

**Database**: SQLAlchemy 1.3 ORM in `database/models.py`, with enums in `model_enums.py`. `DatabaseHandler` provides `get_scoped_session()` context managers. Schema changes need an alembic revision in `alembic/versions/`, plus a version bump so that `Migrator` will run it. `DatabaseHandler.__init__` runs `create_all()` before `Migrator` runs, so new tables (and their indexes) already exist when a migration runs. A migration must skip whatever already exists (see `c4f7a2e9d1b3_add_export_import_and_nicknames.py`), while new columns on existing tables still come only from the migration. Any test that ends up calling `injector.get_database_handler()` must first set `injector.database_handler = DatabaseHandler(in_memory=True)`, or it opens the real user database.

**Reddit data export import** (`utils/importers/reddit_export/`, specific to the fork): it imports the zip Reddit sends for a data request.
- `RedditExportReader` streams the csv files out of the zip (nothing is extracted).
- `RedditExportImporter` upserts posts, comments, chats and private messages. Chats and private messages are stored in the `ChatChannel`, `ChatMessage` and `PrivateMessage` models in `database/export_models.py`.
- `ExportHydrator` can optionally fill in scores and metadata through an adapter's `submissions_by_ids`/`comments_by_ids`.
- `core/export_import_runner.py` runs this on a QThread.
- The import dialog requires a user list. The account and every user in its chats and private messages are added to it (not subreddits or the deleted placeholder); users not yet significant take the list's settings, as in `sync_existing_ro_to_list`. The list's download source is used for hydration, and checkboxes choose whether to hydrate and whether to download media.
- Media linked in chat and private messages becomes `Content` with `chat_message_id` or `private_message_id` and no post. `Content` must always be tied to a post, comment or message; a `before_insert` check in `database/__init__.py` enforces this. `core/message_handler.py` extracts the links (found by `utils/message_links.py`), and `DownloadRunner` takes `chat_message_id_list`/`private_message_id_list`. A message's significant reddit object is its *author*: the author's `download_enabled`, filters and *post* naming/save settings apply, so each author's media goes to the author's own folder (`FilenameGenerator` accepts messages). Use `Content.significant_reddit_object`/`source_date` rather than `content.post.*`.
- The GUI is in `gui/import_reddit_export_dialog.py` (File menu) and `gui/database_views/conversation_viewer.py` (Database menu).
- Chat threads: `database/chat_threads.py` arranges a channel's messages into the timeline, threads (shown in the viewer's thread pane) and reactions.
- Chat reactions (`utils/chat_reactions.py`): a reply whose whole text is one `i.redd.it` GIF or PNG url is a reaction. User uploads come from `matrix.redditspace.com` and never match. Each url is one `ChatReaction` singleton shared by every chat (`ChatMessage.reaction_id`), and `enabled=False` records a user's "not a reaction". Reaction messages are marked extracted and get no `Content`. Their image is stored once in `<data dir>/chat_reactions/` by `core/reaction_fetcher.py`. The viewer shows them as badges, and they are managed in `gui/database_views/reactions_dialog.py` (Database > Chat Reactions).

**Download pipeline** (`core/`): `DownloadRunner` (a QObject that the GUI runs in a QThread) creates a `DownloadSession`, then starts two worker threads joined by queues:
1. The runner fetches submissions for each user or subreddit and pushes them onto `submission_queue`.
2. `ContentRunner` consumes them on a thread pool. For each one, `SubmissionHandler` creates `Post` rows and chooses an extractor.
3. Extracted `Content` goes onto `download_queue`, where `core/download/Downloader` (with `multipart_downloader`) writes the files. `utils/video_merger` merges v.redd.it video and audio through FFmpeg.

All stages share a `threading.Event` called `stop_run`, and `runner.verify_run` checks it.

**Extractors** (`extractors/`): every class subclasses `BaseExtractor`. `SubmissionHandler.assign_extractor` finds them through `BaseExtractor.__subclasses__()` and matches each one's `get_url_key()` against the URL, so a new extractor must be imported in `extractors/__init__.py` and have an entry in `settings_manager.extractor_dict`.

**Data sources** (`data_interface/`): this abstraction is specific to the fork. `RedditDataInterface` (ABC) has three implementations in `adapters/`: `PRAWAdapter` (the Reddit API), `ArcticShiftAdapter` and `PullPushAdapter` (archive APIs). They are selected by the `PostDownloadSource` enum through the singleton `RedditAdapterManager`, which also stores encrypted per-source tokens in settings. `AdapterRedditor`, `AdapterSubmission` and `AdapterSubreddit` wrap results so that core code does not depend on PRAW types. The adapters also handle rate limiting (429 and header parsing).

**Messaging**: background code reports to the GUI output view with `Message.send(...)` or `Message.send_debug(...)` (`messaging/message.py`), which push onto the injector queue. It must never touch widgets directly.

**GUI**: `gui/downloader_for_reddit_gui.py` is the main window. Qt Designer `.ui` sources are in `Resources/ui_files/`, and the generated Python is in `DownloaderForReddit/guiresources/` (the same subfolder layout). Never edit the generated files by hand. Edit the `.ui` file and regenerate it with `Tools/ui_converter.py`. Qt models for list and table views are in `viewmodels/`, and the database browser is in `gui/database_views/`.


## Conventions
- Use spaces for indentation in the codebase, ignore `CONTRIBUTING.md` stylings. 
- The GPL license header must be added to all new files.
- Create loggers as `logging.getLogger(f'DownloaderForReddit.{__name__}')`.
- **Type hints are required**  for all public & private functions; dataclasses for domain models
- **Docstrings are required** for every module, class, and function or method, including private ones and test functions. Sphinx-style `:param:`/`:type:`/`:return:`/`:rtype:` docstrings, and raised exceptions where they apply. Docstrings describe behavior and intent; don't restate the code. (Empty `__init__.py` marker files are the only exception.)
- **No pylint errors, ever.** Error and fatal messages must always be zero.
- **No pylint warnings without individual approval.** This covers messages in pylint's *warning* category only. Fix the code instead whenever reasonable. If a warning cannot reasonably be fixed, stop and ask the user, stating the message name, the exact line, and why it can't be fixed. Only after approval, suppress it with a disable comment **on that single line**, using the symbolic name and a reason: `# pylint: disable=symbolic-name  # approved: reason`.
  - Never use block-level or module-level disables, `# pylint: skip-file`, a `disable=` list in the pylint configuration, or `--disable` on the command line, for any message category. Never add a warning disable without prior approval.
  - Convention and refactor messages are not covered by the approval rule: fix them where reasonable. Where fixing isn't reasonable, a single-line disable with a short reason is acceptable without asking. The docstring, snake_case, final-newline, and trailing-whitespace rules in this section are mandatory regardless of category and must not be suppressed.
  - `.pylintrc` at the repository root is the single pylint configuration. Don't edit it, and don't add `ignored-modules`, `ignore-patterns`, or other exclusions, without the user's approval. If pylint cannot resolve a PyQt6 import, report it to the user instead of suppressing it.
  - Configuration may only change *what is checked*, not silence results: for example `extension-pkg-allow-list` for PyQt6, and `no-docstring-rgx` set so private names are also required to have docstrings (pylint's default exempts names starting with an underscore).
  - `DownloaderForReddit/guiresources/` is machine-generated and is excluded from pylint via `ignore-paths`. This is the only excluded path and is itself subject to the user's approval.
- **Snake case** for functions, methods, variables, parameters, modules, file names, and database table and column names, whenever possible. Python's standard exceptions still apply (PascalCase for classes, UPPER_CASE for constants). **Qt's camelCase names are accepted** where Qt requires them (for example overriding `rowCount`, `data`, or `paintEvent`, or calling Qt methods) and need no individual approval. pylint normally skips naming checks for overridden methods; if it still flags a genuine Qt override, a single-line `# pylint: disable=invalid-name  # Qt override` is allowed without asking. Use it only for methods that override the Qt API; your own methods stay snake_case.
- **Maximum line length is 225 characters** (set in `.pylintrc`; use the same limit in any ruff configuration).
- **Every Python file ends with a newline.** (pylint: `missing-final-newline`; don't suppress.)
- **No trailing whitespace** at the end of any code line, including blank lines inside code. (pylint: `trailing-whitespace`; don't suppress.) Configure editors to strip it on save.
- Logging via `logging`, not `print`. Logging should be lazy not eager
