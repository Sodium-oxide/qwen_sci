# Survey Agent Report: When Will the Universe Die?

## Scope and answerable question

The everyday question "when will the universe die?" conflates several physically distinct events. A useful scientific question is instead: **which late-time expansion histories are permitted by present observations, which cosmic-fate classes follow only after additional asymptotic assumptions, and which future measurements can distinguish them?** This survey treats "death" as a family of fate events rather than a single clock:

1. continued accelerated expansion with progressive dilution and loss of accessible information;
2. a finite-time future singularity such as a Big Rip;
3. turnaround followed by recollapse;
4. a phase transition caused by false-vacuum decay; and
5. astrophysical exhaustion processes, such as the end of ordinary star formation, which are not identical to a global spacetime endpoint.

The proposed research is a **theory-and-observation design study**, not a calculation of an observed end date. It deliberately distinguishes finite-redshift measurements from claims about the limit \(a \rightarrow \infty\), where \(a\) is the cosmic scale factor.

## Evidence corpus and evidence roles

The Survey Agent used dual-engine OpenAlex and AnySearch searches for Planck cosmological parameters, DESI baryon acoustic oscillations (BAO), dark-energy equation-of-state reviews, phantom-energy fates, and electroweak vacuum metastability. Source keys P1-P9 are recorded in "survey_manifest.json"; P1-P8 were returned by both engines for their respective focused queries. A direct browser connection was also attempted because the user requested the in-app browser, but its local runtime exited with a Windows ACL error. No claim in this survey is presented as browser-page verified. Bibliographic metadata are therefore tied to the dual-engine results and DOI identifiers, while publisher-page verification remains a human-review item.

The corpus has three complementary evidence roles.

* **Late-universe measurements.** Planck's final CMB analysis is compatible with spatially flat base Lambda Cold Dark Matter (LambdaCDM) and, when combined with BAO, is consistent with zero curvature within its reported uncertainty [P1]. DESI DR1 BAO measures expansion distances and rates over \(0.1<z<4.2\); in its published parametrized analyses, the baseline flat LambdaCDM model remains viable, while some combinations with supernova data show a dataset-dependent preference for evolving \(w_0,w_a\) descriptions [P2].
* **Inference limits.** The dark-energy review literature describes why expansion and structure-growth probes constrain parameterized descriptions of dark energy but do not directly identify the physical field or guarantee a unique future continuation [P3, P4]. This limitation is central rather than incidental: an empirical fit over an observed range of scale factor is not, by itself, a theorem about its behavior at arbitrary future scale factor.
* **Mechanism-conditioned fate studies.** A sustained constant phantom equation of state can lead to a finite-time Big Rip in the stated model [P5]. A scalar-field potential that later becomes negative can instead recollapse, with its deadline dependent on that potential and fitted parameters [P6]. Electroweak vacuum decay is governed by a distinct tunneling calculation involving particle-physics inputs, renormalization choices, and gravitational assumptions [P7, P8]. It must not be folded into an expansion-history date.

## Scientific background

For a homogeneous and isotropic spacetime, a useful bookkeeping relation is

\[
E^2(a) \equiv \frac{H^2(a)}{H_0^2}
= \Omega_{\mathrm r}a^{-4}+\Omega_{\mathrm m}a^{-3}+\Omega_k a^{-2}
+\Omega_{\mathrm{de}} X_{\mathrm{de}}(a),
\]

where the terms represent radiation, matter, curvature, and a dark-energy contribution. The observational problem estimates \(H(a)\), distances derived from it, and the growth of structure over a finite interval. The fate problem additionally asks how \(X_{\mathrm{de}}(a)\) behaves outside that interval. These are related problems, but not equivalent ones.

If dark energy is a cosmological constant, \(X_{\mathrm{de}}=1\), accelerated expansion asymptotically approaches a de Sitter-like state. This is not a singular "death instant"; it is a continuing expansion in which gravitationally unbound regions become inaccessible and usable free-energy gradients diminish. In a constant-\(w<-1\) phantom model, density grows with scale factor and the integral to \(a\rightarrow\infty\) can be finite, producing a Big Rip [P5]. A quintessence-like or modified-gravity model can yield a different future even if it gives similar distances over the observed redshift interval. A potential crossing to negative total energy can generate a turnaround and eventual collapse [P6].

The parameter pair \(w(a)=w_0+w_a(1-a)\) is often useful for describing departures from a constant equation of state across the observed late universe. It is not automatically safe to evaluate this expression indefinitely into the future: for \(a>1\), its extrapolation can become pathological or encode behavior not intended by the parameterization. Thus a reported \(w_0,w_a\) preference is an observational statement about a chosen family and data combination, not a direct assignment of a cosmic ending.

Vacuum decay is logically separate. A false vacuum may be long lived while expansion continues; it may also decay through bubble nucleation independently of whether the large-scale expansion is asymptotically de Sitter-like. Metastability calculations are sensitive to the Higgs mass, top-quark mass, strong coupling, possible beyond-Standard-Model effects, and the cosmological background [P7, P8]. They warrant a separate evidence channel and a separate unresolved status, not a numerical addition to a Big Rip or heat-death clock.

## Evidence-backed findings

### F1: Current data support a constrained present expansion history, not a measured terminal time

Planck reports consistency of the baseline flat LambdaCDM model with its principal CMB observables and finds curvature consistent with flatness when BAO are included [P1]. DESI DR1 provides high-precision BAO constraints that are compatible with flat LambdaCDM in its baseline analysis, while its time-varying dark-energy fits exhibit data-combination-dependent tensions with LambdaCDM [P2]. These results constrain present and past expansion. They do not observe future evolution and therefore do not identify a universal death date.

### F2: A Big Rip is conditional, not the default interpretation of acceleration

Caldwell, Kamionkowski, and Weinberg show that a constant phantom component, under their stated assumptions, can terminate the expansion in finite proper time [P5]. This supplies a clear conditional mechanism and a falsifiable model family. It does **not** show that a presently fitted value near -1, a transient anomaly, or a two-parameter low-redshift fit implies a Big Rip. The consensus-data result reviewed by Escamilla et al. is compatible with a cosmological constant [P3], which reinforces the need to keep the Big Rip conditional.

### F3: Recollapse is also mechanism-dependent

The negative-potential example examined by Kallosh et al. provides a model where acceleration today can be followed by a future collapse [P6]. It demonstrates non-uniqueness of the fate map, rather than establishing imminent recollapse. Near-flat geometry in a simple LambdaCDM continuation makes a curvature-driven Big Crunch disfavored, but that does not eliminate every dynamical field or modified-gravity route to a turnaround.

### F4: Vacuum-decay risk is a different uncertainty budget

Metastability reviews and decay-rate calculations show that vacuum decay is a quantum-field-theoretic process with large model and parameter sensitivities [P7, P8]. It may be cosmologically catastrophic if it occurs, but current calculations do not yield a model-independent, empirical "universe death" deadline. Any comprehensive fate statement must report expansion fate and vacuum stability on distinct lines.

### F5: Long-term astrophysical change is not equivalent to a spacetime end

In a continued accelerating expansion, sources outside the local gravitationally bound region can cross an event horizon and long-term astrophysical evolution changes observability [P9]. Such milestones are scientifically meaningful but should not be confused with the Big Rip, recollapse, or a vacuum transition. The survey uses the term "asymptotic dilution" for this fate class to avoid falsely implying a dated global event.

## Subhypotheses and coverage

**SH1 - Observational history versus asymptotic continuation.** Multi-probe constraints on \(H(z)\), distances, and growth can rule out portions of parameterized model space, but cannot by themselves prove the \(a\rightarrow\infty\) behavior without an explicit continuation rule. Direct evidence: P1-P4. Coverage: strong for finite-redshift observations; incomplete for asymptotic physics.

**SH2 - Fate separation.** Expansion fates and vacuum-decay fates require separate likelihood inputs and must not be combined into one end-time estimate. Direct evidence: P5-P8. Coverage: strong conceptual and formal separation; incomplete joint treatment.

**SH3 - Model-conditioned singularity claims.** A finite Big Rip time follows from sustained phantom-like dynamics in specified models, not from acceleration alone. Direct evidence: P5. Coverage: direct for the conditional model; no direct evidence that Nature obeys the continuation.

**SH4 - Cross-probe discriminator design.** BAO, CMB, supernovae, weak lensing, redshift drift, and standard sirens have different degeneracies; a designed synthesis should report which addition changes fate classification and why. Direct evidence: P1-P4. Coverage: strong for existing probes; gap in fate-oriented reporting.

## Gap ledger

| Gap ID | Accepted gap | Evidence basis | Scientific consequence |
|---|---|---|---|
| G1 | Finite-range equation-of-state fits are often narrated as infinite-future predictions without a declared continuation class. | P1-P4 | A future date may be unjustified even when parameter constraints are precise. |
| G2 | Expansion history, finite-time singularity, recollapse, and vacuum decay are not reported in one mutually exclusive and condition-aware ledger. | P5-P8 | Different mechanisms can be incorrectly collapsed into one answer. |
| G3 | Standard cosmological analysis emphasizes parameter constraints, not the observational identifiability of fate classes under model extension. | P1-P4 | Similar present-day likelihoods can mask divergent asymptotic futures. |
| G4 | Forecast designs rarely pre-register the transition from a measured observable to a fate claim, including a falsification rule. | P2-P5 | Research can overstate the evidence value of a new probe. |
| G5 | Vacuum stability is frequently mentioned in popular fate narratives without its own particle-physics sensitivity analysis. | P7-P8 | A speculative vacuum statement can be mistaken for a cosmological measurement. |

## Survey conclusion and handoff

The defensible answer is not a scalar number of years. Present observations are compatible with continued accelerated expansion in the standard model and also motivate active tests of time-dependent dark energy. A Big Rip, recollapse, and vacuum decay remain distinct conditional possibilities whose status depends on assumptions not fixed by current finite-redshift data. The handoff therefore asks the Idea Agent to create a falsifiability-first framework that (i) retains every continuation assumption, (ii) maps it to a fate class and time integral only when defined, (iii) lists data channels that can discriminate it, and (iv) returns an explicit "observationally unidentifiable" result whenever current data cannot support a future assertion.

## References

Source keys refer to the frozen registry in "survey_manifest.json". The Author Agent is allowed to cite only the registered sources and the design-artifact assumptions derived from them.
