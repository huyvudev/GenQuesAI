"""framework/config.py — thứ tự ưu tiên: biến môi trường > file > mặc định (ROADMAP C)."""
from __future__ import annotations

from pathlib import Path

from framework import config


def _sach(monkeypatch):
    monkeypatch.delenv("LEGAL_RAG_ROOT", raising=False)
    monkeypatch.delenv("GENQUESAI_CONFIG", raising=False)
    config._doc_file.cache_clear()


def test_khong_co_gi_dung_mac_dinh(monkeypatch):
    _sach(monkeypatch)
    monkeypatch.chdir(Path(__file__).parent)  # thư mục không có genquesai.toml
    assert config.legal_rag_root() == Path(config._MAC_DINH_LEGAL_RAG_ROOT)


def test_file_ghi_de_mac_dinh(tmp_path, monkeypatch):
    _sach(monkeypatch)
    (tmp_path / "genquesai.toml").write_text(
        '[paths]\nlegal_rag_root = "C:/tu-file"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert config.legal_rag_root() == Path("C:/tu-file")


def test_env_ghi_de_file(tmp_path, monkeypatch):
    _sach(monkeypatch)
    (tmp_path / "genquesai.toml").write_text(
        '[paths]\nlegal_rag_root = "C:/tu-file"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LEGAL_RAG_ROOT", "C:/tu-env")
    assert config.legal_rag_root() == Path("C:/tu-env")


def test_genquesai_config_doi_duong_dan_file(tmp_path, monkeypatch):
    _sach(monkeypatch)
    khac = tmp_path / "o-noi-khac.toml"
    khac.write_text('[paths]\nlegal_rag_root = "C:/qua-bien-moi-truong"\n',
                     encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GENQUESAI_CONFIG", str(khac))
    assert config.legal_rag_root() == Path("C:/qua-bien-moi-truong")
