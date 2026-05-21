import unittest


class ElevationTests(unittest.TestCase):
    def test_ensure_elevated_requests_relaunch_on_windows_when_not_admin(self) -> None:
        from dify_win_agent.elevation import ensure_elevated

        calls: list[str] = []

        relaunched = ensure_elevated(
            platform_name="win32",
            is_admin_func=lambda: False,
            relaunch_func=lambda: calls.append("relaunch"),
        )

        self.assertTrue(relaunched)
        self.assertEqual(["relaunch"], calls)

    def test_ensure_elevated_skips_relaunch_when_already_admin(self) -> None:
        from dify_win_agent.elevation import ensure_elevated

        calls: list[str] = []

        relaunched = ensure_elevated(
            platform_name="win32",
            is_admin_func=lambda: True,
            relaunch_func=lambda: calls.append("relaunch"),
        )

        self.assertFalse(relaunched)
        self.assertEqual([], calls)

    def test_ensure_elevated_skips_relaunch_outside_windows(self) -> None:
        from dify_win_agent.elevation import ensure_elevated

        calls: list[str] = []

        relaunched = ensure_elevated(
            platform_name="darwin",
            is_admin_func=lambda: False,
            relaunch_func=lambda: calls.append("relaunch"),
        )

        self.assertFalse(relaunched)
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()