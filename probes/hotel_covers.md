# Cached hotel cover photos

The historical Bright Data Booking cache contained 15 hotels with no photo metadata.
All 15 now retain a real property photograph as optional `card_details` alongside the
original, unchanged room record and Bright Data price provenance. Photo source URLs and
timezone-aware collection timestamps are independent fields retained in the API for internal diagnostics. Customer cards show the
property, booking site and price-check date; collection tools and image-source URLs are
not shown in the Travel interface.
Images remain public remote URLs; they are not generated, stock substitutes, or evidence
of room type, current availability or today's price.

Sources: Chelsea Inn and Golden Gateway public hotel galleries, FOUND Nob Hill and BEI
hotel sites, Nob Hill Motor Inn's public property gallery, Kayak / HotelsCombined property
galleries, and Trip.com's Union Square Plaza gallery. Matches were checked by property
name and street address. A Kayak Union Square gallery contained city/attraction images;
those were rejected in favor of photographs of the actual property on Trip.com.

Run `uv run python scripts/probes/hotel_covers.py` to audit retained photo metadata.
Add `--check-images` to check public image responses, without any Bright Data call or
refresh of prices. Browser QA also checks decoded image dimensions and responsive cards.

Bright Data's primary photo fields continue to be retained for newly collected stays.
Live Bright Data enrichment remains unverified here because no API key is configured.
The six historical Airbnb listings still have no supplied photos; they retain an honest
missing-photo state, with no unrelated apartment substituted.
