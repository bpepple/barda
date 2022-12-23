from barda.settings import BardaSettings


def test_settings(tmpdir):
    user = "test"
    dummy = "dummy_value"

    config = BardaSettings(config_dir=tmpdir)
    # Make sure initial values are correct
    assert not config.metron_user
    assert not config.metron_password
    # Save the new values
    config.metron_user = user
    config.metron_password = dummy
    config.save()
    # Now load that file and verify the contents
    new_config = BardaSettings(config_dir=tmpdir)
    assert new_config.metron_user == user
    assert new_config.metron_password == dummy
