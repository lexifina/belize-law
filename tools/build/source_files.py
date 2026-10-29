"""Where the build finds the retrieved files: the listing (catalogue.json) and one PDF per listed law, named by its
upload id. How they were retrieved is not part of the published record."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache')
BASE = 'https://agm.gov.bz'


def pdf_path(row):
    # Windows paths stop at 260 characters: keep the upload id and at most 100 characters of the name.
    name = row['url'].rsplit('/', 1)[1]
    if len(name) > 110:
        name = name[:100] + '.pdf'
    return os.path.join(CACHE, 'pdf', name)
