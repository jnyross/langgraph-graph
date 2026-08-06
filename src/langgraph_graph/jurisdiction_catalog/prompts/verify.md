# Jurisdiction catalog verification

Assess whether `{{subject}}` belongs in an authoritative operating-jurisdiction
catalog. Use only the supplied search results and fetched source text. Return
the structured fields requested by the caller; do not infer facts that are not
supported by the evidence.

The evidence must discuss the named jurisdiction. If the supplied evidence
does not mention the jurisdiction by name or a clearly recognizable alias,
return `uncertain` regardless of what the source says about another place.

Make two independent judgments:

1. **Services available:** are Facebook, Instagram, or WhatsApp practically
   available to ordinary residents in this jurisdiction?
2. **Authority exists:** does this jurisdiction itself have law-making or
   regulatory authority that can impose obligations relevant to privacy,
   competition, youth safety, intellectual property, or accessibility?

Set `verdict` to `include` only when both judgments are true. Set it to
`exclude` only when at least two supplied sources directly support a blocking
or no-authority conclusion for this named jurisdiction, and confidence is
high. Otherwise set it to `uncertain`; absence of supporting evidence is not
evidence for exclusion. Explain both judgments and cite the supplied evidence
in the rationale. A country, state, province, territory, city, or
supranational body must not be included merely because Meta services are
available there.
