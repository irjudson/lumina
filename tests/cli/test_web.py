"""
Tests for web CLI.

All tests require database connection.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lumina.cli.web import web

pytestmark = pytest.mark.integration


class TestWebCLI:
    """Tests for lumina-web CLI command."""

    def test_web_catalog_not_found(self, tmp_path: Path) -> None:
        """Test error when catalog doesn't exist."""
        runner = CliRunner()
        catalog_path = tmp_path / "nonexistent"

        result = runner.invoke(web, [str(catalog_path)])

        # Should fail with catalog not found message
        # Note: click.Path(exists=True) causes Click to fail early
        assert result.exit_code != 0

    def test_web_catalog_file_missing(self, tmp_path: Path) -> None:
        """Test error when catalog directory exists but catalog not in database."""
        runner = CliRunner()
        catalog_path = tmp_path / "catalog"
        catalog_path.mkdir()

        # Mock CatalogDB to raise an exception (catalog not in database)
        with patch("lumina.cli.web.CatalogDB") as mock_catalog_db:
            mock_catalog_db.side_effect = Exception("Catalog not found")

            result = runner.invoke(web, [str(catalog_path)])

            assert result.exit_code == 0  # Command runs
            assert "Error" in result.output
            assert "lumina-analyze" in result.output

    @patch("lumina.cli.web.uvicorn.run")
    @patch("lumina.cli.web.CatalogDB")
    def test_web_basic_launch(
        self, mock_catalog_db: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test basic web server launch."""
        runner = CliRunner()
        catalog_path = tmp_path / "catalog"
        catalog_path.mkdir()

        # Mock the CatalogDB context manager and query
        mock_db = MagicMock()
        mock_catalog = MagicMock()
        mock_db.session.query.return_value.filter_by.return_value.first.return_value = (
            mock_catalog
        )
        mock_catalog_db.return_value.__enter__.return_value = mock_db

        # Launch web server
        result = runner.invoke(web, [str(catalog_path)])

        assert result.exit_code == 0
        assert "Catalog Viewer" in result.output
        assert "Starting web server" in result.output
        mock_run.assert_called_once()

    @patch("lumina.cli.web.uvicorn.run")
    @patch("lumina.cli.web.CatalogDB")
    def test_web_custom_host_port(
        self, mock_catalog_db: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test custom host and port."""
        runner = CliRunner()
        catalog_path = tmp_path / "catalog"
        catalog_path.mkdir()

        # Mock the CatalogDB context manager and query
        mock_db = MagicMock()
        mock_catalog = MagicMock()
        mock_db.session.query.return_value.filter_by.return_value.first.return_value = (
            mock_catalog
        )
        mock_catalog_db.return_value.__enter__.return_value = mock_db

        # Launch with custom host and port
        result = runner.invoke(
            web, [str(catalog_path), "--host", "0.0.0.0", "--port", "9000"]
        )

        assert result.exit_code == 0
        assert "0.0.0.0:9000" in result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000

    @patch("lumina.cli.web.uvicorn.run")
    @patch("lumina.cli.web.CatalogDB")
    def test_web_reload_mode(
        self, mock_catalog_db: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test reload mode for development."""
        runner = CliRunner()
        catalog_path = tmp_path / "catalog"
        catalog_path.mkdir()

        # Mock the CatalogDB context manager and query
        mock_db = MagicMock()
        mock_catalog = MagicMock()
        mock_db.session.query.return_value.filter_by.return_value.first.return_value = (
            mock_catalog
        )
        mock_catalog_db.return_value.__enter__.return_value = mock_db

        # Launch with reload
        result = runner.invoke(web, [str(catalog_path), "--reload"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["reload"] is True

    @patch("lumina.cli.web.uvicorn.run")
    @patch("lumina.cli.web.CatalogDB")
    def test_web_default_settings(
        self, mock_catalog_db: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Test default host, port, and settings."""
        runner = CliRunner()
        catalog_path = tmp_path / "catalog"
        catalog_path.mkdir()

        # Mock the CatalogDB context manager and query
        mock_db = MagicMock()
        mock_catalog = MagicMock()
        mock_db.session.query.return_value.filter_by.return_value.first.return_value = (
            mock_catalog
        )
        mock_catalog_db.return_value.__enter__.return_value = mock_db

        # Launch with defaults
        result = runner.invoke(web, [str(catalog_path)])

        assert result.exit_code == 0
        assert "127.0.0.1:8765" in result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 8765
        assert call_kwargs["reload"] is False
        assert call_kwargs["log_level"] == "info"
