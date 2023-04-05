import unittest

from technopolis_menu.extractor import parse_menu_simple, verify_menu_structure

# NB: Mandag is missing from this test menu, to test that the parser can handle that.
# ZWNBSP is from the source. Maybe from a WYSIWYG editor?
TEST_MENU = (
    "\ufeff\ufeff\ufeff\ufeff\u00c5pent kl"
    " 10:30-13:00\n\nTirsdag\n\nGulasjsuppe\n\nGrov fiskeburger med fennikelslaw, agurk"
    " og ovnsbakte poteter  Krydderbakte rotgr\u00f8nnsaker, linser, bulgur og"
    " youhurtdressing\n\nOnsdag\n\nPotet og purrel\u00f8ksuppe \n\nGrov fiskeburger med"
    " fennikelslaw, agurk og ovnsbakte poteter  Krydderbakte rotgr\u00f8nnsaker,"
    " linser, bulgur og youhurtdressing\n\nTorsdag\n\nBrokkolisuppe \n\nPanert"
    " r\u00f8dspette med erter, remulade og kokte poteter\n\nBakt potet med div"
    " tilbeh\u00f8r\n\nFredag\n\nLammesuppe \n\nBiff Stroganoff med potetmos \n\nTarte"
    " Flambe med l\u00f8k og squash, servert med ovnsbakt potet- og k\u00e5lsalat\n\n"
)

TEST_MENU_EXPECTED = {
    "mandag": [],
    "tirsdag": [
        "Gulasjsuppe",
        (
            "Grov fiskeburger med fennikelslaw, agurk og ovnsbakte poteter "
            " Krydderbakte rotgrønnsaker, linser, bulgur og youhurtdressing"
        ),
    ],
    "onsdag": [
        "Potet og purreløksuppe",
        (
            "Grov fiskeburger med fennikelslaw, agurk og ovnsbakte poteter "
            " Krydderbakte rotgrønnsaker, linser, bulgur og youhurtdressing"
        ),
    ],
    "torsdag": [
        "Brokkolisuppe",
        "Panert rødspette med erter, remulade og kokte poteter",
        "Bakt potet med div tilbehør",
    ],
    "fredag": [
        "Lammesuppe",
        "Biff Stroganoff med potetmos",
        "Tarte Flambe med løk og squash, servert med ovnsbakt potet- og kålsalat",
    ],
}


class TestExtractor(unittest.TestCase):
    def test_extract(self):
        menu = parse_menu_simple(TEST_MENU)
        self.assertTrue(verify_menu_structure(menu))
        self.assertEqual(menu, TEST_MENU_EXPECTED)
