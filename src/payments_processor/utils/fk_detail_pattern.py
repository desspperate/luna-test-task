import re

FK_DETAIL_PATTERN = re.compile(
    r'Key \((.*?)\)=\((.*?)\) (?:is still referenced from table|is not present in table) "(.*?)"',
)
