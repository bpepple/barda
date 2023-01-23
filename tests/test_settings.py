from barda.settings import BardaSettings


def test_settings(tmpdir):
    user = "test"
    dummy = "dummy_value"
    cv_key = "1234567890"

    config = BardaSettings(config_dir=tmpdir)
    # Make sure initial values are correct
    assert not config.metron_user
    assert not config.metron_password
    assert not config.cv_api_key
    # Save the new values
    config.metron_user = user
    config.metron_password = dummy
    config.cv_api_key = cv_key
    config.save()
    # Now load that file and verify the contents
    new_config = BardaSettings(config_dir=tmpdir)
    assert new_config.metron_user == user
    assert new_config.metron_password == dummy
    assert new_config.cv_api_key == cv_key
