# Standard Reference Crawl Page Range

## Goal

Allow the Standard Reference Library crawler to fetch an inclusive page range
instead of always starting at page 1.

## User Interface

- Replace the single page-count control with start-page and end-page controls.
- Default to pages 1 through 5 to preserve the current default crawl size.
- Both endpoints are included, so 5 through 10 fetches six pages.
- Disable both controls while a crawl is running.
- Reject a range whose end page is earlier than its start page.

## Crawl Flow

- Pass `start_page` and `end_page` through the GUI, backend client, HTTP route,
  and backend service.
- Validate both page numbers within the existing supported page bounds.
- Fetch each page in ascending order from `start_page` through `end_page`.
- Keep progress totals as the number of requested pages, while page records
  retain their actual source page number.
- Preserve cancellation and record de-duplication behavior.

## Verification

- Cover inclusive range iteration and progress counts at the service layer.
- Cover UI submission of both page endpoints and invalid range handling.
- Run the focused standard-reference library and viewer tests.
