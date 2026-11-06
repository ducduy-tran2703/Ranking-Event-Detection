from types import SimpleNamespace
from unittest.mock import Mock

from dotenv import dotenv_values

from eventrank.rag.modal_setup import configure_proxy_access, export_client


def test_client_env_chi_chua_quyen_inference(tmp_path):
    path = tmp_path / "client.env"
    export_client(path, {"MODAL_PROXY_TOKEN_ID": "wk-example",
                         "MODAL_PROXY_TOKEN_SECRET": "ws-example",
                         "RAG_LLM_URL": "https://example.modal.run",
                         "MODAL_TOKEN_SECRET": "as-owner", "R2_SECRET_ACCESS_KEY": "r2-owner",
                         "DATABASE_URL": "postgresql://private"})
    values = dotenv_values(path)
    assert set(values) == {"MODAL_PROXY_TOKEN_ID", "MODAL_PROXY_TOKEN_SECRET", "RAG_LLM_URL"}
    assert values["MODAL_PROXY_TOKEN_SECRET"] == "ws-example"


def test_proxy_workspace_khong_rbac_khong_goi_allow():
    manager = Mock()
    manager.list.return_value = [SimpleNamespace(token_id="wk-example", scoped=False)]
    configure_proxy_access(manager, "wk-example", "main")
    manager.allow.assert_not_called()


def test_proxy_scoped_duoc_cap_quyen_environment():
    manager = Mock()
    manager.list.return_value = [SimpleNamespace(token_id="wk-example", scoped=True)]
    configure_proxy_access(manager, "wk-example", "main")
    manager.allow.assert_called_once_with("wk-example", "main")
