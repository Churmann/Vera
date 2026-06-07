# TODO

Follow-ups, not blockers.

## Better-alternatives

- [ ] **Coca-Cola still triggers some retried 429s.** The rate-limit retry/backoff
  recovers, but high-traffic products like Coca-Cola can still hit several retried
  429s per lookup. Could optimise further (e.g. tighter concurrency ceiling, longer
  backoff, or caching category-search results).
- [ ] **Add a "relatedness" refinement to category matching.** Same-category search
  can still suggest products that aren't true substitutes — e.g. a chocolate spread
  surfacing peanut butter or margarine instead of other sweet spreads. Consider
  refining candidate selection so suggestions stay within the same product sub-type.

## Future enhancements

- [ ] **Let users submit data for products missing from Open Food Facts (photos +
  composition), the way Yuka handles coverage gaps** — since the crowd-sourced
  database has incomplete data for some products.
