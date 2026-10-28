from capture_style import read_tokens, tokens_from_file, tokens_from_measure


def test_the_app_buttons_give_the_accent_and_the_page_its_background():
    measured = {
        "body": {"background": "rgb(246, 247, 251)", "color": "rgb(21, 22, 26)",
                 "font": '"Manrope", system-ui'},
        "h1": {"font": '__Fraunces_1a2b3c, serif'},
        "backgrounds": [["rgb(246, 247, 251)", 9], ["rgb(255, 255, 255)", 5]],
        "colors": [["rgb(21, 22, 26)", 40], ["rgb(255, 255, 255)", 6], ["rgb(100, 104, 112)", 5]],
        "buttons": [{"background": "rgb(79, 70, 229)", "radius": "10px"},
                    {"background": "rgba(0, 0, 0, 0)", "radius": "10px"}],
        "cards": [],
    }
    t = tokens_from_measure(measured)
    assert t["--bg"] == "#F6F7FB"
    assert t["--surface"] == "#FFFFFF"
    assert t["--accent"] == "#4F46E5" and t["--accent-ink"] == "#FFFFFF"
    assert t["--muted"] == "#646870"  # grey text, never the white of a button label
    assert t["--font-heading"].startswith('"Fraunces"')
    assert t["--font-body"].startswith('"Manrope"')


def test_a_transparent_body_falls_back_to_the_page_background():
    t = tokens_from_measure({"html": {"background": "rgb(16, 20, 24)"},
                             "body": {"background": "rgba(0, 0, 0, 0)", "color": "rgb(240, 240, 240)"}})
    assert t["--bg"] == "#101418"


def test_shadcn_css_variables(tmp_path):
    css = tmp_path / "globals.css"
    css.write_text(":root { --background: 0 0% 100%; --foreground: 222 84% 5%; --primary: 142 71% 35%;"
                   " --muted-foreground: 215 16% 47%; --radius: 0.75rem; --font-sans: Manrope; }")
    t, mapping = tokens_from_file(read_tokens(css))
    assert t["--accent"] == "hsl(142 71% 35%)" and mapping["--accent"] == "primary"
    assert t["--ink"] == "hsl(222 84% 5%)"
    assert t["--muted"] == "hsl(215 16% 47%)"
    assert t["--radius"] == "0.75rem"
    assert t["--font-heading"] == t["--font-body"] == '"Manrope", system-ui, sans-serif'


def test_w3c_json_tokens(tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text('{"color": {"brand": {"primary": {"$value": "#F0C000"}},'
                      ' "text": {"default": {"$value": "#111111"}, "subtle": {"$value": "#666666"}}}}')
    t, _ = tokens_from_file(read_tokens(tokens))
    assert t["--accent"] == "#F0C000"
    assert t["--accent-ink"] == "#111111"  # dark text on a light accent
    assert t["--ink"] == "#111111" and t["--muted"] == "#666666"
