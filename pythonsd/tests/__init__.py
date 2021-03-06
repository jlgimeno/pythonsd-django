"""General tests for site setup and functionality.

Specific tests relating to one app should be in that package.
"""

import importlib
import json
import os
import shutil
import stat
import unittest
from unittest import mock

from django import test
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings
import webtest

import tasks
from config import wsgi
from .. import static_files


class TestRedirectViews(test.TestCase):
    """Ensure project redirects function correctly."""

    def test_home_redirect(self):
        """The root path '/' should redirect to '/index.html'
        in order to work with the reverse proxy.
        """
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/index.html")

    def test_coc_redirect(self):
        """The shortcut '/coc' path should redirect to
        the code of conduct page."""
        response = self.client.get("/coc")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/pages/code-of-conduct.html")


class TestMeetupWidget(test.TestCase):
    """Test the Meetup.com widget of upcoming events"""

    def setUp(self):
        fp = os.path.join(os.path.dirname(__file__), "data/meetup-events-api.json")
        with open(fp) as fd:
            self.api_response = json.load(fd)

        self.expected_events = [
            {
                "link": "https://www.meetup.com/pythonsd/events/fdzbnqyznbqb/",
                "name": "Saturday Study Group",
                "datetime": "2019-10-12T12:00:00-07:00",
                "venue": "UCSD Geisel Library",
            },
            {
                "link": "https://www.meetup.com/pythonsd/events/fdzbnqyznbzb/",
                "name": "Saturday Study Group",
                "datetime": "2019-10-19T12:00:00-07:00",
                "venue": "UCSD Geisel Library",
            },
            {
                "link": "https://www.meetup.com/pythonsd/events/zgtnxqyznbgc/",
                "name": "Monthly Meetup",
                "datetime": "2019-10-24T19:00:00-07:00",
                "venue": "Qualcomm Building Q",
            },
        ]

    @mock.patch("pythonsd.views.MeetupWidget.get_upcoming_events", return_value=[])
    def test_no_events(self, mock_call):
        response = self.client.get("/meetup-widget.html")
        self.assertContains(response, "No upcoming events")

    def test_html_widget(self):
        with mock.patch("pythonsd.views.requests.get") as mock_get:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = self.api_response
            response = self.client.get("/meetup-widget.html")
        self.assertTrue("text/html" in response["Content-Type"])
        self.assertContains(response, "UCSD Geisel Library")
        self.assertContains(response, "Qualcomm Building Q")

    def test_cors(self):
        with mock.patch("pythonsd.views.requests.get") as mock_get:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = self.api_response
            response = self.client.get("/meetup-widget.html")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

        with mock.patch("pythonsd.views.requests.get") as mock_get:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = self.api_response
            response = self.client.get("/meetup-widget.json")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_json_widget(self):
        with mock.patch("pythonsd.views.requests.get") as mock_get:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = self.api_response
            response = self.client.get("/meetup-widget.json")
        expected = json.dumps(self.expected_events, cls=DjangoJSONEncoder)
        self.assertJSONEqual(response.content.decode("utf-8"), expected)

    def test_api_failure(self):
        with mock.patch("pythonsd.views.requests.get") as mock_get:
            mock_get.return_value.ok = False
            response = self.client.get("/meetup-widget.json")
            self.assertJSONEqual(response.content.decode("utf-8"), "[]")

        with mock.patch("pythonsd.views.requests.get") as mock_get:
            mock_get.side_effect = Exception
            response = self.client.get("/meetup-widget.json")
            self.assertJSONEqual(response.content.decode("utf-8"), "[]")


@mock.patch(
    "revproxy.views.HTTP_POOLS.urlopen", return_value=mock.MagicMock(status=200)
)
class TestProxyViews(test.TestCase):
    """Any path not served by this Django app should proxy to the static site."""

    def test_unserved_path(self, mock_urlopen):
        """Any path without a normal URL pattern should default to the proxy view."""
        mock_path = "mock-path"
        self.client.get("/" + mock_path, follow=True)
        args, kwargs = mock_urlopen.call_args
        self.assertEqual(args[1], settings.PYTHONSD_STATIC_SITE + mock_path)


class TestCSSCompiling(unittest.TestCase):
    """Test the custom static 'Finder' class for static file compiling."""

    @mock.patch("tasks.build", wraps=tasks.build)
    def test_compile_collectstatic(self, mock_call):
        """A subprocess call to 'make' should be made."""
        compile_finder = static_files.CompileFinder()
        compile_finder.list("mock argument")
        mock_call.assert_called_once_with()

    def test_missing_destination(self):
        shutil.rmtree(tasks.CSS_DIR)
        tasks.build()

    def test_existing_desintation(self):
        shutil.rmtree(tasks.CSS_DIR)
        os.makedirs(tasks.CSS_DIR)
        tasks.build()

    @mock.patch("os.makedirs", side_effect=OSError)
    def test_other_exception(self, mock_makedirs):
        self.assertRaises(OSError, tasks.build)


class TestWSGIApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = webtest.TestApp(wsgi.application)

    def test_admin_login(self):
        """Test that the admin login can be reached through the WSGI App.

        This test is mostly to exercise the interface.
        """
        response = self.app.get("/admin/login/")
        self.assertEqual(response.status_int, 200)
