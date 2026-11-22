# DownloaderForReddit Architecture Flow Diagram

## 1. Dependency Injection Wiring

```
┌─────────────────┐    ┌──────────────────┐
│   Injector      │    │   Component      │
│                 │    │   Providers      │
├─────────────────┤    ├──────────────────┤
│ get_message_queue() ──▶ MessageQueue       │
│ get_database_handler() ──▶ DatabaseHandler     │
│ get_scheduler() ──▶ Scheduler              │
│ get_settings_manager() ──▶ SettingsManager      │
└─────────────────┘    └──────────────────┘

        ▲
        │
        │ (dependency injection)
        │
┌─────────────────┐
│   Main.py       │
│                 │
│ 1. Creates QApplication │
│ 2. Gets components via injector │
│ 3. Passes to GUI and other modules │
└─────────────────┘
```

## 2. Component Interaction Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   DownloaderForRedditGUI │    │   MessageReceiver │    │   Scheduler     │
│                 │    │                 │    │                 │
│ - User Actions  │    │ - Message Queue │    │ - Scheduled     │
│ - Triggers      │    │ - Distributes   │    │   Downloads     │
│   Downloads     │    │   Messages      │    │ - Time-based    │
│                 │    │ - Qt Signals    │    │   Triggering    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                          ┌─────────────────┐
                          │   Core Download │
                          │   Components    │
                          │                 │
                          │ - Downloader    │
                          │ - Extractor     │
                          │ - DatabaseHandler│
                          │ - SettingsManager│
                          └─────────────────┘
```

## 3. Threading Model

```
┌─────────────────┐
│   QApplication  │
│   (Main Thread) │
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│   GUI Thread    │
│  ┌─────────────┐│
│  │ DownloaderForRedditGUI ││
│  └─────────────┘│
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│   Message Thread│
│  ┌─────────────┐│
│  │ MessageReceiver ││
│  └─────────────┘│
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│   Scheduler Thread│
│  ┌─────────────┐│
│  │ Scheduler   ││
│  └─────────────┘│
└─────────────────┘
```

## 4. Message Passing Architecture

```
┌─────────────────┐
│   DownloaderForRedditGUI │
├─────────────────┤
│  User Actions   │
│  (download, etc)│
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│   MessageQueue  │
│  ┌─────────────┐│
│  │   Messages  ││
│  └─────────────┘│
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│   MessageReceiver │
│  ┌─────────────┐│
│  │ Distributes ││
│  │ Messages    ││
│  └─────────────┘│
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│   Components    │
│  ┌─────────────┐│
│  │ Downloader  ││
│  │ Extractor   ││
│  │ Database    ││
│  └─────────────┘│
└─────────────────┘
```

## Signal/Slot Connections

```
┌─────────────────┐
│   MessageReceiver │
│  text_output ──▶│
│                 │
│  non_text_output ──▶│
└─────────────────┘
         ▲
         │
         │ Qt Signals
         │
┌─────────────────┐
│   DownloaderForRedditGUI │
│  handle_message   │
│  handle_progress  │
└─────────────────┘
```