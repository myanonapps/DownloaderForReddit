#!/usr/bin/env python

import sys
import os
import subprocess

# The repository root, found from this file's location so the converter works from any working directory.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Converter:

    # Relative to REPO_ROOT, which pyuic6 is run in, so the paths written into the generated files stay relative.
    base_ui_path = os.path.join('Resources', 'ui_files')
    base_out_path = os.path.join('DownloaderForReddit', 'guiresources')

    def __init__(self, ui_file):
        self.ui_file = ui_file

        self.callable_methods = [
            'about',
            'add_reddit_object',
            'core_settings',
            'database_dialog',
            'database_settings',
            'display_settings',
            'download_settings',
            'export_wizard',
            'notification_settings',
            'output_settings',
            'filter_input',
            'filter_widget',
            'main_window',
            'object_info',
            'object_settings',
            'quick_filter_settings',
            'reddit_object_dialog',
            'schedule_settings',
            'settings',
            'update_dialog',
            'invalid_dialog',
            'existing_names_dialog',
            'database_viewer',
            'import_reddit_export_dialog',
            'conversation_viewer',
            'reactions_dialog',
            'backup_dialog',
        ]

    def run(self) -> int:
        """
        Converts the chosen .ui file, asking for one first when 'list' was given.
        :return: The process exit code: 0 on success, 1 when the name is unknown or pyuic6 fails.
        :rtype: int
        """
        if self.ui_file == 'list':
            self.list_methods()
            self.ui_file = input('GUI file name (or number): ')
        try:
            method = getattr(self, self.get_method())
        except AttributeError:
            print('Command not recognized.  Choices are: ')
            self.list_methods()
            return 1
        try:
            method()
        except subprocess.CalledProcessError as error:
            print(f'Conversion failed (pyuic6 exit code {error.returncode})')
            return 1
        print('Conversion successful')
        return 0

    def get_method(self):
        try:
            index = int(self.ui_file)
            return self.callable_methods[index]
        except ValueError:
            return self.ui_file

    def list_methods(self):
        for x, y in enumerate(self.callable_methods):
            print(f'{x}: {y}')

    def convert(self, name: str, *sub_paths: str) -> None:
        """
        Runs pyuic6 on one .ui file, writing the generated Python to the matching place under guiresources.  pyuic6 is
        run from the repository root with this interpreter's PyQt6, so it works from any working directory and without
        pyuic6 on the PATH.
        :param name: The .ui file's name, without extension.
        :type name: str
        :param sub_paths: The subfolders the file is in, under both the ui_files and guiresources folders.
        :type sub_paths: str
        :return: None
        :rtype: None
        :raises subprocess.CalledProcessError: When pyuic6 fails.
        """
        in_path = self.get_in_path(name, *sub_paths)
        out_path = self.get_out_path(name, *sub_paths)
        subprocess.run([sys.executable, '-m', 'PyQt6.uic.pyuic', in_path, '-o', out_path], cwd=REPO_ROOT, check=True)

    def get_in_path(self, name, *sub_paths):
        name = f'{name}.ui'
        return os.path.join(self.base_ui_path, *sub_paths, name)

    def get_out_path(self, name, *sub_paths):
        name = f'{name}_auto.py'
        return os.path.join(self.base_out_path, *sub_paths, name)

    def about(self):
        name = 'about_dialog'
        self.convert(name)

    def add_reddit_object(self):
        name = 'add_reddit_object_dialog'
        self.convert(name)

    def main_window(self):
        name = 'downloader_for_reddit_gui'
        self.convert(name)

    def reddit_object_dialog(self):
        name = 'reddit_object_settings_dialog'
        self.convert(name)

    def update_dialog(self):
        name = 'update_dialog'
        self.convert(name)

    def database_dialog(self):
        name = 'database_dialog'
        self.convert(name, 'database_views')

    def database_viewer(self):
        name = 'database_viewer'
        self.convert(name, 'database_views')

    def filter_input(self):
        name = 'filter_input_widget'
        self.convert(name, 'database_views')

    def filter_widget(self):
        name = 'filter_widget'
        self.convert(name, 'database_views')

    def core_settings(self):
        name = 'core_settings_widget'
        self.convert(name, 'settings')

    def database_settings(self):
        name = 'database_settings_widget'
        self.convert(name, 'settings')

    def display_settings(self):
        name = 'display_settings_widget'
        self.convert(name, 'settings')

    def download_settings(self):
        name = 'download_settings_widget'
        self.convert(name, 'settings')

    def export_wizard(self):
        name = 'export_wizard'
        self.convert(name)

    def notification_settings(self):
        name = 'notification_settings_widget'
        self.convert(name, 'settings')

    def output_settings(self):
        name = 'output_settings_widget'
        self.convert(name, 'settings')

    def quick_filter_settings(self):
        name = 'quick_filter_settings_widget'
        self.convert(name, 'settings')

    def schedule_settings(self):
        name = 'schedule_settings_widget'
        self.convert(name, 'settings')

    def settings(self):
        name = 'settings_dialog'
        self.convert(name, 'settings')

    def object_info(self):
        name = 'object_info_widget'
        self.convert(name, 'widgets')

    def object_settings(self):
        name = 'object_settings_widget'
        self.convert(name, 'widgets')

    def invalid_dialog(self):
        name = 'invalid_reddit_object_dialog'
        self.convert(name)

    def existing_names_dialog(self):
        name = 'existing_names_dialog'
        self.convert(name)

    def import_reddit_export_dialog(self):
        name = 'import_reddit_export_dialog'
        self.convert(name)

    def conversation_viewer(self):
        name = 'conversation_viewer'
        self.convert(name, 'database_views')

    def reactions_dialog(self):
        name = 'reactions_dialog'
        self.convert(name, 'database_views')

    def backup_dialog(self):
        name = 'backup_dialog'
        self.convert(name)

    def user_auth_wizard(self):
        name = 'user_auth_wizard'
        self.convert(name)


def main():
    try:
        command = sys.argv[1]
    except IndexError:
        print('No class specified')
        command = input('GUI Name (or number): ')
    converter = Converter(command)
    sys.exit(converter.run())


if __name__ == '__main__':
    main()
