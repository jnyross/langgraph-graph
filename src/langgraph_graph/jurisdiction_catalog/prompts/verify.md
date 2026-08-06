# Jurisdiction catalog verification

Assess whether `{{subject}}` belongs in an authoritative operating-jurisdiction
catalog. Use only the supplied search results and fetched source text. Return
the structured fields requested by the caller; do not infer facts that are not
supported by the evidence.

Make two independent judgments:

1. **Services available:** are Facebook, Instagram, or WhatsApp practically
   available to ordinary residents in this jurisdiction?
2. **Authority exists:** does this jurisdiction itself have law-making or
   regulatory authority that can impose obligations relevant to privacy,
   competition, youth safety, intellectual property, or accessibility?

Set `verdict` to `include` only when both judgments are true. Set it to
`exclude` when reliable evidence shows either judgment is false. Otherwise set
it to `uncertain`. Explain both judgments and cite the supplied evidence in the
rationale. A country, state, province, territory, city, or supranational body
must not be included merely because Meta services are available there.
