import json
import logging
import subprocess
from pathlib import WindowsPath, Path

from .app_settings import AppSettings
from .fsr_cfg import FsrSettings
from .fsr_mod import FsrMod
from .globals import USER_APP_PREFIX, get_data_dir, get_version
from .manifest_worker import ManifestWorker
from .utils import capture_app_exceptions
from .valve import steam


def reduce_steam_apps_for_export(steam_apps) -> dict:
    reduced_dict = dict()

    for app_id, entry in steam_apps.items():
        fsr = FsrMod(entry)

        reduced_dict[app_id] = dict()
        # Add only necessary data
        reduced_dict[app_id]['settings'] = fsr.settings.to_js(export=True)
        reduced_dict[app_id]['fsrInstalled'] = entry.get('fsrInstalled')
        reduced_dict[app_id]['fsrVersion'] = entry.get('fsrVersion')
        reduced_dict[app_id]['fsr_compatible'] = entry.get('fsr_compatible', True)
        reduced_dict[app_id]['name'] = entry.get('name')
        reduced_dict[app_id]['sizeGb'] = entry.get('sizeGb')
        reduced_dict[app_id]['path'] = entry.get('path')
        reduced_dict[app_id]['openVrDllPaths'] = entry.get('openVrDllPaths')
        reduced_dict[app_id]['openVrDllPathsSelected'] = entry.get('openVrDllPathsSelected')
        reduced_dict[app_id]['openVr'] = entry.get('openVr')
        reduced_dict[app_id]['SizeOnDisk'] = entry.get('SizeOnDisk')
        reduced_dict[app_id]['appid'] = entry.get('appid')

    return reduced_dict


@capture_app_exceptions
def _load_steam_apps_with_fsr_settings():
    """ Load SteamApps from disk and restore complete settings entries """
    steam_apps = AppSettings.load_steam_apps()
    for app_id, entry in steam_apps.items():
        fsr = FsrMod(entry)
        entry['settings'] = fsr.settings.to_js(export=False)
    return steam_apps


@capture_app_exceptions
def _save_steam_lib(steam_apps):
    logging.info('Updating SteamApp disk cache.')

    # -- Save disk cache without User Apps
    #    and update AppSettings User App entries
    remove_ids = set()
    for app_id, entry in steam_apps.items():
        if not app_id:
            continue
        if entry.get('_showDetails'):
            entry.pop('_showDetails')
        if entry.get('userApp', False) is True or app_id.startswith(USER_APP_PREFIX):
            remove_ids.add(app_id)
    for app_id in remove_ids:
        user_entry = steam_apps.pop(app_id)
        AppSettings.user_apps[app_id] = user_entry

    AppSettings.save_steam_apps(reduce_steam_apps_for_export(steam_apps))
    AppSettings.save()


@capture_app_exceptions
def load_steam_lib_fn():
    """ Load saved SteamApps from disk """
    steam_apps = _load_steam_apps_with_fsr_settings()

    re_scan_required = False

    # -- Re-create disk cache between versions
    if get_version() != AppSettings.previous_version:
        re_scan_required = True

    # -- Re-scan lib if no cached apps other than user apps
    if not len(steam_apps.keys()):
        re_scan_required = True

    logging.debug(f'Loaded {len(steam_apps.keys())} Steam Apps from disk.')

    # -- Add User Apps
    steam_apps.update(AppSettings.user_apps)

    return json.dumps({'result': True, 'data': steam_apps, 'reScanRequired': re_scan_required})


@capture_app_exceptions
def get_steam_lib_fn():
    """ Refresh SteamLib and re-scan every app directory """
    logging.debug('Reading Steam Library')
    try:
        # -- Read this machines Steam library
        steam.apps.read_steam_library(find_open_vr=True)

        # -- Create a local copy of Steam Apps dict
        steam_apps = dict()
        steam_apps.update(steam.apps.steam_apps)

        # -- Remove Library Paths helper entry
        steam_apps.pop(steam.STEAM_LIBRARY_FOLDERS)
    except Exception as e:
        msg = f'Error getting Steam Lib: {e}'
        logging.error(msg)
        # for app_id, manifest in steam_apps.items():
        #     logging.debug(f'{app_id} {manifest.get("name")}')
        return json.dumps({'result': False, 'msg': msg})

    logging.debug('Acquiring OpenVR Dll locations for %s Steam Apps.', len(steam_apps.keys()))
    steam_apps = ManifestWorker.update_steam_apps(steam_apps)

    # -- Restore FSR settings cached on disk and determine if cache and disk are out of sync
    cached_steam_apps = _load_steam_apps_with_fsr_settings()
    for app_id, entry in cached_steam_apps.items():
        if app_id in steam_apps:
            steam_apps[app_id]['settings'] = entry['settings']
            steam_apps[app_id]['openVrDllPathsSelected'] = entry['openVrDllPathsSelected']

    # -- Add User Apps
    AppSettings.load()
    steam_apps.update(AppSettings.user_apps)

    # -- Cache updated SteamApps to disk
    try:
        _save_steam_lib(steam_apps)
    except Exception as e:
        msg = f'Error saving Steam Lib data: {e}'
        logging.error(msg)
        return json.dumps({'result': False, 'msg': msg})

    logging.debug('Providing Front End with Steam Library [%s]', len(steam_apps.keys()))
    return json.dumps({'result': True, 'data': steam_apps})


@capture_app_exceptions
def remove_custom_app_fn(app: dict):
    if app.get('appid') not in AppSettings.user_apps:
        return json.dumps({'result': False, 'msg': f'Could not find app with Id: {app.get("appid")}'})

    entry = AppSettings.user_apps.pop(app.get('appid'))
    AppSettings.save()
    logging.debug('App entry: %s %s removed', entry.get('name'), entry.get('appid'))
    return json.dumps({'result': True, 'msg': f'App entry {entry.get("name")} {entry.get("appid")} created.'})


@capture_app_exceptions
def add_custom_app_fn(app: dict):
    # -- Check path
    if app.get('path') in (None, ''):
        return json.dumps({'result': False, 'msg': 'No valid path provided.'})

    path = Path(app.get('path'))
    if not path.exists():
        return json.dumps({'result': False, 'msg': 'Provided path does not exist.'})

    for app_id, entry in AppSettings.user_apps.items():
        if entry.get('path') == path.as_posix():
            return json.dumps({'result': False, 'msg': f'Entry already exists as '
                                                       f'{entry.get("name")}, Id: {app_id}.'})

    # -- Check and find OpenVR
    openvr_paths = [p for p in ManifestWorker.find_open_vr_dll(path)]
    if not openvr_paths:
        return json.dumps({'result': False, 'msg': f'No OpenVR dll found in: {path.as_posix()} or any sub directory.'})

    # -- Find installed FSR
    f = FsrSettings()
    cfg_results = list()
    for p in openvr_paths:
        cfg_results.append(f.read_from_cfg(p.parent))

    # -- Add User App entry
    AppSettings.user_app_counter += 1
    app_id = f'{USER_APP_PREFIX}{AppSettings.user_app_counter:03d}'
    logging.debug('Creating User App entry %s', app_id)
    AppSettings.user_apps[app_id] = {
            'appid': app_id,
            "name": app.get('name', app_id),
            'path': path.as_posix(),
            'openVrDllPaths': [p.as_posix() for p in openvr_paths],
            'openVrDllPathsSelected': [p.as_posix() for p in openvr_paths],
            'openVr': True,
            'settings': f.to_js(),
            'fsrInstalled': any(cfg_results),
            'sizeGb': 0, 'SizeOnDisk': 0,
            'userApp': True,
    }
    AppSettings.save()

    return json.dumps({'result': True, 'msg': f'App entry {app_id} created.'})


@capture_app_exceptions
def get_fsr_dir_fn():
    if AppSettings.openvr_fsr_dir is not None and Path(AppSettings.openvr_fsr_dir).exists():
        open_fsr_dir = str(WindowsPath(AppSettings.openvr_fsr_dir))
        logging.info('Providing FSR Dir to FrontEnd: %s', open_fsr_dir)
        return open_fsr_dir


@capture_app_exceptions
def set_fsr_dir_fn(directory_str):
    if not directory_str:
        directory_str = str(WindowsPath(get_data_dir() / 'openvr_fsr'))
    return json.dumps({'result': AppSettings.update_fsr_dir(directory_str)})


@capture_app_exceptions
def update_fsr_fn(manifest: dict):
    fsr = FsrMod(manifest)
    cfg_result = fsr.update_cfg()

    if cfg_result:
        fsr.manifest['fsrVersion'] = fsr.get_fsr_version()
    else:
        logging.error('Error updating Fsr config!')

    return json.dumps({'result': all((cfg_result, not fsr.error)),
                       'msg': fsr.error, 'manifest': fsr.manifest})


@capture_app_exceptions
def install_fsr_fn(manifest: dict):
    fsr = FsrMod(manifest)
    install_result = fsr.install()
    if install_result:
        fsr.manifest['fsrVersion'] = fsr.get_fsr_version()
    return json.dumps({'result': install_result, 'msg': fsr.error, 'manifest': fsr.manifest})


@capture_app_exceptions
def uninstall_fsr_fn(manifest: dict):
    fsr = FsrMod(manifest)
    uninstall_result = fsr.uninstall()
    if uninstall_result:
        fsr.manifest['fsrVersion'] = str()
    return json.dumps({'result': uninstall_result, 'msg': fsr.error, 'manifest': fsr.manifest})


@capture_app_exceptions
def launch_app_fn(manifest: dict):
    app_id = manifest.get('appid')
    if not app_id:
        return json.dumps({'result': False, 'msg': 'Could not find valid Steam App ID'})

    # steam_path = Path(steam.apps.find_steam_location()) / 'steam.exe'
    # cmd = [str(WindowsPath(steam_path)), '-applaunch', app_id]
    cmd = f'explorer "steam://rungameid/{app_id}"'
    logging.info('Launching %s', cmd)

    subprocess.Popen(cmd)
    return json.dumps({'result': True, 'msg': f'Launched: {cmd}'})
