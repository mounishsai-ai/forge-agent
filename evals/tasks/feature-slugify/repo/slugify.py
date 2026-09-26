def slugify(text, max_length=None):
    """
    Convert text into a URL-friendly slug.

    Rules:
    - Unicode characters should be transliterated to their closest ASCII
      equivalent where possible using Unicode NFKD normalization and then
      dropping any remaining non-ASCII characters (e.g. "cafe" from
      "café", "naive" from "naïve").
    - Convert everything to lowercase.
    - Replace every run of one or more characters that are NOT a
      lowercase ASCII letter, digit, or hyphen with a single hyphen.
      (This means spaces, punctuation, underscores, and repeated
      separators like "--" or " - " all collapse to one "-".)
    - Strip any leading or trailing hyphens from the result.
    - If max_length is given (a positive int), truncate the result to at
      most max_length characters, then strip any trailing hyphen left
      dangling by the cut.
    - Empty input, or input with no valid characters left after
      processing, returns "".

    Examples:
        slugify("Hello, World!") == "hello-world"
        slugify("  Multiple   spaces  ") == "multiple-spaces"
        slugify("café naïve") == "cafe-naive"
        slugify("a---b__c") == "a-b-c"
        slugify("Trailing---", max_length=9) == "trailing"
        slugify("") == ""
        slugify("!!!") == ""
    """
    raise NotImplementedError
