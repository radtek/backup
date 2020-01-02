import argparse
import json
import logging
import shutil
import filecmp
from os import path, mkdir, makedirs, listdir, sep, walk, unlink, symlink
from datetime import datetime
from sys import stdout


def ask_before_backup(notifications):
    for question in notifications:
        if not input(f"{question} [y/n]\n").lower().startswith('y'):
            quit()


def do_copy(src, dst):
    global prev_backups, working_folder
    prev_version_path = ''
    for backup_name in prev_backups:
        path_to_find = f"{working_folder}{sep}{backup_name}{sep}{src.replace(':', sep).lstrip(sep)}"
        if path.exists(path_to_find):
            prev_version_path = path_to_find
            break
    if not (prev_version_path and filecmp.cmp(src, prev_version_path)):
        logging.info(f'Copy {src}')
        return shutil.copy2(src, dst)
    else:
        logging.info(f'Skip {src}')

def abort(msg):
    logging.error(msg)
    quit()


if __name__ == '__main__':
    print("= = = = = = = = = = = = = = = = =", file=stdout)
    print("=      IT'S TIME TO BACKUP      =", file=stdout)
    print("= = = = = = = = = = = = = = = = =\n", file=stdout)
    arg_parser = argparse.ArgumentParser(description='This script performs incremental file backup.',
                                         epilog='For more information please see readme.md.')
    arg_parser.add_argument('-c', type=str, default=path.join(path.dirname(__file__), 'backup.json'),
                            help='Absolute path to configuration file, current_folder/backup.json is default.')
    args = arg_parser.parse_args()
    with open(args.c, 'r', encoding='utf-8') as f:
        config = json.load(f)

    if config.get('notifications'):
        ask_before_backup(config['notifications'])

    logging.basicConfig(level=logging.INFO)

    for link in config['links']:
        if path.exists(link['dst']):
            if path.islink(link['dst']):
                unlink(link['dst'])
            else:
                abort(f"{link['dst']} is not a symlink")
        if '?' in link['src']:
            mounted_folder = listdir(link['src'][:link['src'].index('?')])
            if not isinstance(mounted_folder, list) or len(mounted_folder) != 1:
                abort(f"Unable to define mounted folder: {mounted_folder}")
            link['src'] = link['src'].replace('?', mounted_folder[0])
        symlink(link['src'], link['dst'])
        logging.info(f"Link updated: {link['src']} -> {link['dst']}")

    logging.info('Backup started')
    prev_handler = None
    for device_num, device in enumerate(config['devices'], 1):
        logging.info(f"{device['name'].upper()} (device {str(device_num)} of {len(config['devices'])})")
        working_folder = path.join(device['path'], device['working_folder'])

        if device['type'] == 'not_supported':
            logging.info(f"Need to do manual copy to {working_folder}")
            ask_before_backup([f['path'] for f in device['sources']])
            continue

        makedirs(working_folder, exist_ok=True)
        target_folder = path.join(working_folder, datetime.now().strftime('%Y%m%d'))
        log_folder = path.join(working_folder, 'logs')
        makedirs(log_folder, exist_ok=True)
        log_handler = logging.FileHandler(path.join(log_folder, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"),
                                          encoding='utf-8')
        log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S'))
        log_handler.setLevel(logging.INFO)
        logger = logging.getLogger()
        if prev_handler:
            logger.removeHandler(prev_handler)
        logger.addHandler(log_handler)
        prev_handler = log_handler

        logging.info('Checking sources')
        for source in device['sources']:
            if not path.exists(source['path']):
                abort(f"Source not exists: {source['path']}")

        logger.info('Preparing target device')
        if not path.exists(device['path']):
            abort(f"Device path ot found: {device['path']}")
        disk_usage = shutil.disk_usage(device['path'])
        if disk_usage.free / 1024 / 1024 / 1024 > device['free_space_threshold_gb']:
            logging.info(f'OK: (total {disk_usage.total / 1024 / 1024 / 1024 :1.2f} Gb; '
                         f'used {disk_usage.used / 1024 / 1024 / 1024 :1.2f} Gb; '
                         f'free {disk_usage.free / 1024 / 1024 / 1024 :1.2f} Gb)')
        else:
            abort(f'Free space threshold exceeded: {disk_usage.free / 1024 / 1024 / 1024 :1.2f} Gb')
        prev_backups = sorted([d for d in listdir(working_folder) if d.split(sep)[-1].isdigit()], reverse=True)
        if prev_backups:
            logging.info(f"Previous backups found {','.join(prev_backups)[:21]}...")
        else:
            logging.info(f"It seems to be initial (full) backup")
        try:
            mkdir(target_folder)
            logging.info(f'Created {target_folder}')
        except FileExistsError:
            abort(f'Target folder "{target_folder}" already exists, please cleanup')

        logging.info('Copying data')
        for source in device['sources']:
            try:
                src_path = source['path']
                dst_path = f"{target_folder}{sep}{source['path'].replace(':', sep).lstrip(sep)}"
                ignore = [*source.get('ignore', []), *config['ignore']]
                if path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, ignore=shutil.ignore_patterns(*ignore), copy_function=do_copy)
                else:
                    makedirs(path.dirname(dst_path), exist_ok=True)
                    do_copy(src_path, dst_path)
            except shutil.Error as e:
                abort(str(e))

        logging.info('Postprocessing')
        total_size = total_files = 0
        for folder, _, files in walk(target_folder):
            for file in files:
                total_size += path.getsize(path.join(folder, file))
                total_files += 1
        logging.info(f'{total_files} files copied, ({total_size / 1024 / 1024 / 1024 :1.2f} Gb)')
        logging.info(f"Backup to {device['name'].upper()} device finished")
