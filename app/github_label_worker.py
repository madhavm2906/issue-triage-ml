from time import monotonic, sleep

import httpx

from app.github_app import github_client, load_settings, verified_token
from app.github_label_sender import deliver, delivery_error, load_review
from app.label_worker import PermanentLabelError, RetryableLabelError, run_once

POLL_SECONDS = 2
TOKEN_REFRESH_SECONDS = 30 * 60
GITHUB_RETRY_SECONDS = 5


def get_write_token(client, settings):
    while True:
        try:
            return verified_token(client, settings, permission="write")
        except httpx.HTTPStatusError as exc:
            error = delivery_error(exc.response)
            if not isinstance(error, RetryableLabelError):
                raise error from exc
            delay = max(GITHUB_RETRY_SECONDS, error.retry_after)
        except httpx.RequestError:
            delay = GITHUB_RETRY_SECONDS

        print(f"GitHub connection unavailable. Retrying in {delay} seconds.", flush=True)
        sleep(delay)


def work(client, settings):
    token = get_write_token(client, settings)
    refresh_at = monotonic() + TOKEN_REFRESH_SECONDS
    print(f"Watching approved label updates for {settings.repository}.", flush=True)

    review_id = None
    pause = 0

    def send(job):
        nonlocal token, review_id, pause
        review_id = job["review_id"]

        try:
            snapshot = load_review(review_id, settings.repository)
        except RuntimeError as exc:
            raise PermanentLabelError(str(exc)) from exc

        try:
            deliver(client, settings, token, snapshot, job)
        except RetryableLabelError as exc:
            pause = max(GITHUB_RETRY_SECONDS, exc.retry_after)
            raise
        except PermanentLabelError as exc:
            cause = exc.__cause__
            if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 401:
                token = None
                raise RetryableLabelError("GitHub rejected the token. Refreshing it.") from exc
            raise

    while True:
        if token is None or monotonic() >= refresh_at:
            token = get_write_token(client, settings)
            refresh_at = monotonic() + TOKEN_REFRESH_SECONDS

        review_id = None
        pause = 0
        state = run_once(send, repository=settings.repository)

        if review_id is not None:
            print(f"Review {review_id} | {state}", flush=True)

        if pause:
            sleep(pause)
        elif state is None:
            sleep(POLL_SECONDS)


def main():
    try:
        settings = load_settings()
        with github_client() as client:
            work(client, settings)
    except KeyboardInterrupt:
        print("\nGitHub label worker stopped.", flush=True)
    except (RuntimeError, PermanentLabelError, OSError) as exc:
        raise SystemExit(f"GitHub label worker stopped: {exc}") from None


if __name__ == "__main__":
    main()
