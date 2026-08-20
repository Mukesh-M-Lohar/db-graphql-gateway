from click.testing import CliRunner

from db_graphql_gateway.cli.main import cli


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Generate secure GraphQL APIs from your database" in result.output


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "sgql" in result.output


def test_cli_init() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "Initialization complete" in result.output


def test_cli_inspect() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect"])
    # Should fail without --dsn
    assert result.exit_code == 1
    assert "DATABASE_URL" in result.output


def test_cli_generate() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["generate"])
    assert result.exit_code == 0
    assert "GraphQL schema generated" in result.output


def test_cli_validate() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["validate"])
        # Without sgql.yaml, it should fail
        assert result.exit_code == 1
        assert "not found" in result.output


def test_cli_diff() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["diff"])
    assert result.exit_code == 0
    assert "No schema drift detected" in result.output


def test_cli_security() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["security"])
    assert result.exit_code == 0
    assert "Security audit passed" in result.output


def test_cli_doctor() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "db-graphql-gateway doctor checks" in result.output


def test_cli_test() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["test"])
    assert result.exit_code == 0
    assert "Tests passed" in result.output
