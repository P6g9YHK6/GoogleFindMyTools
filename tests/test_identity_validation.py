from webui import identity_validation


def test_validate_display_name():
    assert identity_validation._validate_display_name("My Tracker") is None
    assert identity_validation._validate_display_name("") is not None
    assert identity_validation._validate_display_name("x" * 41) is not None
    assert identity_validation._validate_display_name('bad"name') is not None
    assert identity_validation._validate_display_name("bad\\name") is not None


def test_validate_manufacturer():
    assert identity_validation._validate_manufacturer("Acme") is None
    assert identity_validation._validate_manufacturer("") is not None
    assert identity_validation._validate_manufacturer("x" * 41) is not None


def test_validate_model():
    assert identity_validation._validate_model("Tag v2") is None
    assert identity_validation._validate_model("") is not None
    assert identity_validation._validate_model("x" * 41) is not None


def test_validate_device_type():
    for name in identity_validation.DEVICE_TYPE_CHOICES:
        assert identity_validation._validate_device_type(name) is None
    assert identity_validation._validate_device_type("DEVICE_TYPE_UNKNOWN") is not None
    assert identity_validation._validate_device_type("NOT_A_REAL_TYPE") is not None
    assert identity_validation._validate_device_type("") is not None


def test_validate_image_url():
    assert identity_validation._validate_image_url("https://example.com/x.png") is None
    assert identity_validation._validate_image_url("http://example.com/x.png") is None
    assert identity_validation._validate_image_url("") is not None
    assert identity_validation._validate_image_url("ftp://example.com/x.png") is not None
    assert identity_validation._validate_image_url("not-a-url") is not None
    assert identity_validation._validate_image_url("https://" + "x" * 2048) is not None
