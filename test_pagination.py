import unittest

from pagination import paginate


class PaginationTests(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate([10, 20, 30, 40, 50], 1, 2), [10, 20])

    def test_second_page(self):
        self.assertEqual(paginate([10, 20, 30, 40, 50], 2, 2), [30, 40])

    def test_partial_last_page(self):
        self.assertEqual(paginate([10, 20, 30, 40, 50], 3, 2), [50])

    def test_beyond_last_page(self):
        self.assertEqual(paginate([10, 20], 3, 2), [])

    def test_empty(self):
        self.assertEqual(paginate([], 1, 2), [])

    def test_does_not_mutate_input(self):
        items = [10, 20, 30]
        result = paginate(items, 1, 2)
        result.append(999)
        self.assertEqual(items, [10, 20, 30])

    def test_invalid_parameters(self):
        for page, per_page in ((0, 2), (-1, 2), (1, 0), (1, -1),
                               (True, 2), (1, False), (1.5, 2), (1, "2")):
            with self.subTest(page=page, per_page=per_page):
                with self.assertRaises(ValueError):
                    paginate([10, 20, 30], page, per_page)


if __name__ == "__main__":
    unittest.main()

