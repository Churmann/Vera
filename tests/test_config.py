from app.config import Settings


def test_default_environment_is_production():
    s = Settings(_env_file=None)
    assert s.off_environment == "production"
    assert s.is_staging is False
    assert s.off_product_host == "world.openfoodfacts.org"


def test_staging_environment_maps_to_net_host():
    s = Settings(off_environment="staging", _env_file=None)
    assert s.is_staging is True
    assert s.off_product_host == "world.openfoodfacts.net"


def test_credentials_default_to_none():
    s = Settings(_env_file=None)
    assert s.off_username is None
    assert s.off_password is None
