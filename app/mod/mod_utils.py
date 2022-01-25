from pathlib import Path, WindowsPath
from typing import Dict

import app.mod
from app.app_settings import AppSettings
from app.globals import get_data_dir
from app.mod import BaseModType


def get_mod(manifest, mod_type):
    """ Get Mod Class Object by int type specifier

    :param dict manifest:
    :param int mod_type:
    :rtype: app.mod.base_mod.BaseMod
    """
    mod_type_class = getattr(app.mod, BaseModType.mod_types.get(mod_type))
    return mod_type_class(manifest)


def get_available_mods(manifest):
    """ Get iterator with available Mod Types

    :param dict manifest:
    :rtype: list[app.mod.base_mod.BaseMod]
    """
    for mod_type in BaseModType.mod_types.keys():
        yield get_mod(manifest, mod_type)


def check_mod_data_dir(custom_data_dir: Path, mod_type: int):
    if custom_data_dir and Path(custom_data_dir).exists():
        mod = get_mod(dict(), mod_type)
        dll_exists = Path(Path(custom_data_dir) / mod.DLL_NAME).exists()
        cfg_exists = Path(Path(custom_data_dir) / mod.settings.CFG_FILE).exists()
        if dll_exists and cfg_exists:
            return True
    return False


def update_mod_data_dirs() -> Dict[int, str]:
    mod_dirs = dict()

    for mod_type in BaseModType.mod_types.keys():
        data_dir_name = BaseModType.mod_data_dir_names[mod_type]
        mod_dirs[mod_type] = str(WindowsPath(get_data_dir() / data_dir_name))

        custom_src_data_dir = AppSettings.mod_data_dirs.get(mod_type)

        if check_mod_data_dir(custom_src_data_dir, mod_type):
            mod_dirs[mod_type] = custom_src_data_dir

    AppSettings.mod_data_dirs.update(mod_dirs)
    return mod_dirs
