from flask import Response
from flask import request
from functools import wraps
from oauth2client.client import OAuth2WebServerFlow
from PIL import Image
from re import compile as re_compile

from epd import DISPLAY_WIDTH
from epd import DISPLAY_HEIGHT
from firestore import Firestore
from graphics import draw_text
from graphics import SUBVARIO_CONDENSED_MEDIUM
from response import text_response

# The color of the new user image background.
BACKGROUND_COLOR = (255, 0, 0)

# The color used for the new user image text.
TEXT_COLOR = (255, 255, 255)

# The scope to request for the Google Calendar API.
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

# The URL where Google Calendar access can be revoked.
ACCOUNT_ACCESS_URL = "https://myaccount.google.com/permissions"

# The regular expression a user key has to match.
KEY_PATTERN = re_compile("^[a-zA-Z0-9]+$")


def _forbidden_response():
    """Creates a simple forbidden status response."""

    return Response(status=403)


def settings_url(key):
    """Creates the URL for user data settings."""

    return "https://%s/hello/%s" % (request.host, key)


def verify_scope(scope):
    """Checks if the provided scope is an expected one."""

    return scope in [GOOGLE_CALENDAR_SCOPE]


def _settings_response(key, image_func):
    """Creates an image response to start the new user flow."""

    # Draw the image with the link text.
    image = Image.new(mode="RGB", size=(DISPLAY_WIDTH, DISPLAY_HEIGHT),
                      color=BACKGROUND_COLOR)
    draw_text(settings_url(key),
              font_spec=SUBVARIO_CONDENSED_MEDIUM,
              text_color=TEXT_COLOR,
              anchor="center",
              image=image)

    return image_func(image)


def _valid_key(key):
    """Checks if a user key's format is as expected."""

    return KEY_PATTERN.fullmatch(key)


def validate_key(func):
    """A decorator for Flask route functions to enforce valid keys."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not _valid_key(kwargs["key"]):
            return _forbidden_response()

        return func(*args, **kwargs)

    return wrapper


def user_auth(image_func=None):
    """A decorator for Flask route functions to enforce user authentication."""

    firestore = Firestore()

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Look for a key debug request argument first.
                key = request.args["key"]
            except KeyError:
                # Otherwise, expect a basic access authentication header.
                authorization = request.authorization
                if not authorization:
                    return _forbidden_response()
                key = authorization["password"]

            # Disallow malformed keys.
            if not _valid_key(key):
                return _forbidden_response()

            # Look up the user from the key.
            user = firestore.user(key)
            if not user:
                if image_func:
                    # For image requests, start the new user flow.
                    return _settings_response(key, image_func)
                else:
                    # Otherwise, return a forbidden response.
                    return _forbidden_response()

            # Inject the key and user into the function arguments.
            kwargs["key"] = key
            kwargs["user"] = user
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _oauth_redirect_url():
    """Creates the URL handling OAuth redirects."""

    return "http://%s/oauth" % request.host


def _google_calendar_flow(key):
    """Creates the OAuth flow."""

    secrets = Firestore().google_calendar_secrets()
    return OAuth2WebServerFlow(client_id=secrets["client_id"],
                               client_secret=secrets["client_secret"],
                               scope=GOOGLE_CALENDAR_SCOPE,
                               state=key,
                               redirect_uri=_oauth_redirect_url())


def google_calendar_step1(key):
    """Creates the URL for the first OAuth step."""

    # The user key is passed through the flow as state.
    flow = _google_calendar_flow(key)
    return flow.step1_get_authorize_url(state=key)


def google_calendar_step2(key, code):
    """Creates the URL for the second OAuth step."""

    flow = _google_calendar_flow(key)
    return flow.step2_exchange(code=code)