def test_path_options(parser, tmpdir):
    parsed = parser.parse_args([str(tmpdir)])
    assert parsed.path == [str(tmpdir)]
