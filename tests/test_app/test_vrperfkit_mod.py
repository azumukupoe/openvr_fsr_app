import json

from app import app_fn
from app.openvr_mod import OpenVRModType
from app.vrperfkit_mod import VRPerfKitMod


def test_update_mod_fn(test_app, output_path, vrperfkit_dll_output, vrperfkit_mod_cfg_output):
    mod_settings = test_app[VRPerfKitMod.VAR_NAMES['settings']]
    test_setting_key = 'method'
    test_setting_parent_key = 'upscaling'
    test_setting_value = 'nis'

    # -- Manipulate a setting
    for s in mod_settings:
        if s.get('key') == test_setting_key:
            s['value'] = test_setting_value

    # -- Point to test output dir
    test_app['executablePaths'] = [vrperfkit_dll_output.as_posix()]
    test_app['executablePathsSelected'] = [vrperfkit_dll_output.as_posix()]

    # -- Test Fn
    result_dict = json.loads(app_fn.update_mod_fn(test_app, OpenVRModType.vrp, True))

    # -- Check returned manifest setting
    result_manifest_setting_value = None
    for s in result_dict['manifest'][VRPerfKitMod.VAR_NAMES['settings']]:
        if s.get('key') == test_setting_key:
            result_manifest_setting_value = s['value']

    # -- Read settings back
    mod = VRPerfKitMod(test_app)
    mod.update_from_disk()

    assert result_dict['result'] is True
    assert result_manifest_setting_value == test_setting_value

    val = mod.settings._get_option_by_key(test_setting_key, test_setting_parent_key).value
    assert val == test_setting_value

    # -- Cleanup output
    vrperfkit_dll_output.unlink()
    vrperfkit_mod_cfg_output.unlink()


def test_toggle_mod_install_fn(test_app_writeable):
    exe_locations = test_app_writeable['executablePaths']

    # -- Test OpenVR Mod installation
    result_dict = json.loads(app_fn.toggle_mod_install_fn(test_app_writeable, OpenVRModType.vrp))
    assert result_dict['result'] is True

    # -- Test OpenVR Mod uninstallation
    result_dict = json.loads(app_fn.toggle_mod_install_fn(test_app_writeable, OpenVRModType.vrp))
    assert result_dict['result'] is True