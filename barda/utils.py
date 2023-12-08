import platform
import re
from os import environ
from pathlib import Path, PurePath

from bs4 import BeautifulSoup
from titlecase import titlecase
from xdg.BaseDirectory import save_config_path


def get_settings_folder() -> Path:
    """Method to determine where the users settings should be saved."""

    if platform.system() != "Windows":
        return Path(save_config_path("barda"))

    windows_path = PurePath(environ["APPDATA"]).joinpath("Barda")
    return Path(windows_path)


def clean_desc(txt: str) -> str:
    # No text, let's bail.
    if not txt:
        return ""
    split_txt = txt.split("\n\n")
    split_len = len(split_txt)
    # If the description starts with 'Content' let's return an empty string.
    if split_len < 2 and split_txt[0].lower().startswith("content"):
        return ""
    # If there are 2 or more paragraphs, check to see if the last paragraph starts with 'Content'
    # and if so let's not join it to the return string.
    if split_len > 1:
        for idx, i in enumerate(split_txt):
            item = str(i).strip("\n")
            if (
                item.lower().startswith("content")
                or item.lower().startswith("note")
                or item.lower().startswith("story")
                or item.lower().startswith("chapter")
                or item.lower().startswith("synopsis")
            ):
                return "\n\n".join(split_txt[:idx]) if split_len > 2 else split_txt[0]
        else:
            return txt
    return txt


def remove_overview_text(txt: str) -> str:
    """Remove overview text from beginning of a string if present."""
    if not txt:
        return txt
    words = txt.split()
    if words[0].lower() in {"overview", "overview:"}:
        return " ".join(txt.split()[1:])
    return txt


def clean_search_series_title(title: str) -> str:
    new_string = title.lower()
    if new_string.startswith("the "):
        new_string = new_string.replace("the ", "", 1)
    # new_string = new_string.replace(" & ", " ")
    # new_string.replace(" and ", " ")
    return new_string.replace(" / ", "/")


def fix_story_chapters(story: str) -> str:
    story_types = ["chapter", "part", "conclusion"]
    lower_story_str = story.lower()
    for t in story_types:
        idx = lower_story_str.find(t)
        # Nothing found. Let's check the next type
        if idx == -1:
            continue
        # Check for hyphen
        hyphen_idx = lower_story_str.find(f"- {t}")
        if hyphen_idx != -1:
            story = f"{lower_story_str[:hyphen_idx].strip()},{lower_story_str[hyphen_idx + 1:]}"
            return titlecase(story)
        fist_char_before = idx - 1
        second_char_before = idx - 2
        if lower_story_str[fist_char_before] == " ":
            if lower_story_str[second_char_before] == ",":
                # Nothing to fix.
                return titlecase(story)
            lower_story_str = lower_story_str.replace(f" {t}", f", {t}")
            return titlecase(lower_story_str)
        if lower_story_str[fist_char_before] == "," and lower_story_str[second_char_before] != " ":
            # This will add a space after each comma, which should be alright.
            lower_story_str = lower_story_str.replace(",", ", ")
            return titlecase(lower_story_str)
            # TODO: Handle cases where the story type if enclosed in parenthesis.
    return titlecase(story)


def cleanup_html(
    string: str | None, remove_html_tables: bool
) -> str:  # sourcery skip: low-code-quality
    """
    converter = html2text.HTML2Text()
    #converter.emphasis_mark = '*'
    #converter.ignore_links = True
    converter.body_width = 0
    print(html2text.html2text(string))
    return string
    #return converter.handle(string)
    """

    if string is None:
        return ""
    # find any tables
    soup = BeautifulSoup(string, "html.parser")
    tables = soup.findAll("table")

    # remove all newlines first
    string = string.replace("\n", "")

    # put in our own
    string = string.replace("<br>", "\n")
    string = string.replace("</p>", "\n\n")
    string = string.replace("<h4>", "*")
    string = string.replace("</h4>", "*\n")

    # remove the tables
    p = re.compile(r"<table[^<]*?>.*?<\/table>")
    if remove_html_tables:
        string = p.sub("", string)
        string = string.replace("*List of covers and their creators:*", "")
    else:
        string = p.sub("{}", string)

    # now strip all other tags
    p = re.compile(r"<[^<]*?>")
    newstring = p.sub("", string)

    newstring = newstring.replace("&nbsp;", " ")
    newstring = newstring.replace("&amp;", "&")

    newstring = newstring.strip()

    if not remove_html_tables:
        # now rebuild the tables into text from BSoup
        try:
            table_strings = []
            for table in tables:
                hdrs = []
                col_widths = []
                for hdr in table.findAll("th"):
                    item = hdr.string.strip()
                    hdrs.append(item)
                    col_widths.append(len(item))
                rows = [hdrs]
                for row in table.findAll("tr"):
                    cols = []
                    col = row.findAll("td")
                    for i, c in enumerate(col):
                        item = c.string.strip()
                        cols.append(item)
                        if len(item) > col_widths[i]:
                            col_widths[i] = len(item)
                    if cols:
                        rows.append(cols)
                # now we have the data, make it into text
                fmtstr = "".join(f" {{:{w + 1}}}|" for w in col_widths)
                width = sum(col_widths) + len(col_widths) * 2
                print("width=", width)
                table_text = ""
                for counter, row in enumerate(rows):
                    table_text += fmtstr.format(*row) + "\n"
                    if counter == 0 and hdrs:
                        table_text += "-" * width + "\n"
                table_strings.append(table_text)

            newstring = newstring.format(*table_strings)
        except AttributeError:
            # we caught an error rebuilding the table.
            # just bail and remove the formatting
            print("table parse error")
            newstring.replace("{}", "")

    return newstring
