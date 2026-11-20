# SS-QTSO-DISPLAYTERM

QT/SO create/update from the CRM without `displayTerm`: SS fills it from the
debtor's own AutoCount term (read from AutoCount for that book). Debtor with no
term in AutoCount -> stable refusal `DEBTOR_TERM_MISSING` (with debtor code)
instead of AutoCount's `FIELD_REQUIRED: displayTerm`. An explicit
`displayTerm` sent by the caller is kept unchanged. Writes stay behind the
existing db3-only write guard.

Tests (red first): no term -> debtor term used; explicit term -> kept;
debtor without term -> DEBTOR_TERM_MISSING.
