from epaper_studio.cli import main
from epaper_studio.config import Settings


def test_env_file_and_environment(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text('# comment\nPORT=9000\nTAG_ADDRESS="aa:bb:cc:00:12:34"\nexport BLE_WRITE_DELAY_MS=30\n')
    s = Settings.load(env, environ={"PORT": "9100"})
    assert s.port == 9100  # the environment wins
    assert s.tag_address == "AA:BB:CC:00:12:34"
    assert s.ble_write_delay == 0.03
    defaults = Settings.load(tmp_path / "missing", environ={"XDG_DATA_HOME": str(tmp_path)})
    assert (defaults.host, defaults.port, defaults.tag_address) == ("0.0.0.0", 8080, "")
    assert defaults.data_dir == tmp_path / "epaper-studio"
    assert not defaults.https


def test_https_and_data_dir(tmp_path) -> None:
    s = Settings.load(None, environ={"SSL_CERTFILE": "c.pem", "SSL_KEYFILE": "k.pem", "DATA_DIR": str(tmp_path)})
    assert s.https and s.data_dir == tmp_path


def test_init_writes_template_once(tmp_path) -> None:
    env = tmp_path / ".env"
    assert main(["--init", "--env-file", str(env)]) == 0
    assert "TAG_ADDRESS=" in env.read_text()
    assert main(["--init", "--env-file", str(env)]) == 1
