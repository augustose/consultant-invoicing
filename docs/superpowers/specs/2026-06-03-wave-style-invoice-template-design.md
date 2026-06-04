# Wave-Style Invoice Template Design

## Goal

Create a custom invoice template that closely matches the supplied Wave invoice PDF while removing the "Powered by Wave" label. Update the existing database records so Augusto Sosa Escalada is the invoice issuer and the existing Cafe Parvis customer contains the complete contact details from the PDF.

## Scope

- Replace the active custom invoice template at `data/invoice_template_custom.html`.
- Keep one Cafe Parvis customer record and update it in place.
- Update company settings with Augusto Sosa Escalada's invoice identity.
- Update or create the IT Consulting and Support service shown in the PDF.
- Update invoice numbering so the next invoice number is `100123`.
- Do not import invoice `100121` unless requested separately.

## Visual Design

The template will use a letter-page invoice layout inspired by the reference PDF:

- Dark charcoal header with a large `INVOICE` title on the left.
- Medium-gray amount-due block on the right.
- Spacious two-column body with Bill To details on the left and invoice metadata on the right.
- Uppercase table headers for items, quantity, price, and amount.
- Light gray item row with the description text below the service name.
- Totals aligned to the right, including GST and QST numbers.
- Notes / Terms section below the totals.
- Footer with issuer identity and contact information.
- No Wave branding or "Powered by Wave" label.

## Data Updates

Company settings:

- Legal name: `Augusto Sosa Escalada (Mac)`
- Address: `1464, Fronenac St. App.#1\nMontreal, Quebec H2K 2Y7\nCanada`
- Phone: `5148853146`
- GST: `717569891 RT 0001`
- QST: `4023119175 TQ 0002`
- Currency: `CAD`

Existing Cafe Parvis customer:

- Name: `Cafe Parvis`
- Contact: `Alejandra Ponce`
- Email: `alejandraponce@hotmail.com`
- Phone: `514 775 5234`
- Address: `433 Rue Mayor\nMontréal, Quebec H3A 1N9\nCanada`
- Currency: `CAD`

Service:

- Name: `IT Consulting and Support`
- Description: `Monthly Subscription for Technical Support of Existing IT Infrastructure.`
- Unit price: `600.00`
- Active: yes

Invoice numbering:

- Last sent invoice number: `100122`
- Last sent invoice date: `April 30, 2026`
- Last sent payment due date: `April 30, 2026`
- Last sent amount due: `$689.85`
- Next invoice number to issue: `100123`
- New invoices should use sequential numeric invoice numbers instead of the existing `INV-...` timestamp-style format.

## Rendering Details

The current renderer passes prebuilt `line_items` HTML into the Jinja template. The new template will continue to consume the existing context variables and will not require schema changes. Tax labels will use the current company GST/QST values from settings when available; otherwise the template will still render sensible defaults.

Invoice creation should call a small numbering helper. The helper should find numeric invoice numbers already stored in the database, compare them with the known external baseline `100122`, and return one greater than the highest value. This lets the app issue `100123` next even though the last Wave invoice is not stored in the local database.

## Verification

- Render an invoice preview through `/preview/{id}`.
- Confirm the custom template is active.
- Confirm the Wave branding is absent.
- Confirm the Cafe Parvis and company settings records contain the PDF details.
- Confirm the next generated invoice number is `100123`.
- Run focused tests or a render smoke check for `TemplateManager.render_invoice`.
