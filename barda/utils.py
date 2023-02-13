import re

from bs4 import BeautifulSoup


def cleanup_html(string, remove_html_tables):  # sourcery skip: low-code-quality
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
