# 4. Graduation

> [!NOTE]
> **In one minute.** A crude death rate is a count divided by a count, and counts are noisy: even in a country of 130 million people, the number of deaths at age 53 in one year is partly luck. A life table built on those raw rates would zigzag, and every price built on it would inherit the zigzag. **Graduation** draws a smooth curve through the crude rates, with a stated rule for how smooth is smooth enough, a measure of how much uncertainty is left, and a set of tests that say whether the curve has thrown away something real.
>
> **What this chapter does:** it turns the crude rates of [chapter 3](03-crude-rates.md) into the graduated rates that [chapter 5](05-life-tables.md) builds life tables on. It derives the two smoothers the project uses (Whittaker-Henderson and the Poisson P-spline), the rule that chooses their smoothness, the two parametric laws they are compared with, the old-age closure that carries the table to age 110, and the tests that judge every fit.
>
> **The number to remember.** In 2023 the P-spline's deviance (a measure of misfit, section 4.3) was 99 for women and 129 for men; Heligman-Pollard, the classic eight-parameter law, was **8.8 and 8.7 times worse**. A smooth law is not a smooth curve through the data: the data have shapes a law does not allow.

Code: `src/mortality/graduation.py` · Tests: `tests/test_graduation.py` and `tests/test_handbook_graduation.py` · Results: [graduation.md](../graduation.md)

**Local symbols** (everything else is in the [notation](01-notation.md)). $`\mathcal{D}_x,\ \mathcal{E}_x,\ \hat m_x`$ are the deaths, central exposure and crude rate at age $`x`$ of one year and sex. $`\mu_x^{*} = \mathcal{E}_x\, m_x`$ is the **expected** number of deaths. $`\theta`$ are spline coefficients, $`\lambda`$ the smoothing parameter, $`\psi`$ the dispersion, $`\boldsymbol\Delta^{k}`$ the matrix that takes $`k`$-th differences, and $`\mathbf{W} = \mathrm{diag}(w_x)`$ a matrix of weights.

**Contents.** [4.1](#41-the-model-deaths-are-poisson-counts) the model · [4.2](#42-measuring-misfit-deviance-and-residuals) deviance · [4.3](#43-whittaker-henderson) Whittaker-Henderson · [4.4](#44-the-poisson-p-spline) P-spline · [4.5](#45-how-smooth-is-smooth-enough) choosing smoothness · [4.6](#46-two-laws-and-a-closure-curve) laws · [4.7](#47-tests-of-fit) tests of fit · [4.8](#48-closing-the-table-at-the-oldest-ages) old-age closure · [4.9](#49-a-fit-you-can-check-by-hand) worked example · [4.10](#410-validation) validation · [4.11](#411-code-map) code map · [4.12](#412-limits) limits

---

## 4.1 The model: deaths are Poisson counts

Within one year and sex, treat the number of deaths at age $`x`$ as a **Poisson** count whose mean is the exposure times the true central rate:

$$
\mathcal{D}_x \sim \mathrm{Poisson}(\mathcal{E}_x\, m_x), \qquad \hat m_x = \frac{\mathcal{D}_x}{\mathcal{E}_x}. \tag{4.1}
$$

The crude rate $`\hat m_x`$ is the maximum-likelihood estimate of $`m_x`$ when each age is considered alone. It is unbiased, and its variance is $`m_x / \mathcal{E}_x`$, which is *large relative to the rate* when deaths are few. The cleaner way to see the noise is on the log scale. For a Poisson count with mean $`\mu^{*}`$ the delta method ($`\log D \approx \log \mu^{*} + (D - \mu^{*})/\mu^{*}`$) gives

$$
\mathrm{Var}(\log \hat m_x) \approx \frac{1}{\mu_x^{*}} \approx \frac{1}{\mathcal{D}_x}. \tag{4.2}
$$

**The relative noise depends only on the number of deaths.** At age 53 in 2023, 3,268 women and 5,522 men died, so the standard deviation of $`\log \hat m`$ is about 1.7% and 1.3%: small. At age 5, with 230 and 295 deaths, it is about 6.6% and 5.8%. Two consequences shape everything below: the crude curve is *not* smooth even where it is precise, because real mortality is smooth and the wiggles are noise; and the weight each age deserves in a fit is its number of deaths.

> [!NOTE]
> The data in this project are **overdispersed**: the scatter between neighbouring ages is larger than (4.2) allows, because registration quirks, rounding of reported ages and population estimates add variation that is not sampling luck. Section 4.5 measures by how much.

## 4.2 Measuring misfit: deviance and residuals

How far is a fitted curve $`m_x`$ from the data? The **Poisson deviance** compares the log-likelihood of the fitted model with that of a "saturated" one that fits every count exactly ($`\hat\mu_x^{*} = \mathcal{D}_x`$):

$$
\mathrm{Dev} = 2 \sum_x \left[ \mathcal{D}_x \log\frac{\mathcal{D}_x}{\mu_x^{*}} - \left(\mathcal{D}_x - \mu_x^{*}\right) \right] = 2\left[\log L_{\text{saturated}} - \log L_{\text{fitted}}\right]. \tag{4.3}
$$

It is zero for a perfect fit and grows with misfit. When the fitted counts are close to the data it is approximately Pearson's chi-square, $`\sum_x (\mathcal{D}_x - \mu_x^{*})^2 / \mu_x^{*}`$, which is the sum of squares of the **standardized residuals**

$$
z_x = \frac{\mathcal{D}_x - \mu_x^{*}}{\sqrt{\mu_x^{*}}}. \tag{4.4}
$$

If the model were right and the data Poisson, each $`z_x`$ would be roughly a standard normal draw, so about $`2\,\Phi(-2) = 4.55\%`$ of them should lie beyond $`\pm 2`$. That 4.55% is the benchmark used in section 4.7.

## 4.3 Whittaker-Henderson

The oldest method in actuarial science (Whittaker, 1922; Henderson, 1924) says: *find the curve closest to the data, but punish roughness.* Work with $`y_x = \log \hat m_x`$ and look for fitted values $`z_x = \log m_x`$ that minimise

$$
\underbrace{\sum_x w_x\,(y_x - z_x)^2}_{\text{fidelity to the data}} \;+\; \lambda \underbrace{\sum_x \left(\Delta^{k} z_x\right)^2}_{\text{roughness}}, \qquad w_x = \mathcal{D}_x. \tag{4.5}
$$

Here $`\Delta^k z_x = \sum_{j=0}^{k}(-1)^{k-j}\binom{k}{j} z_{x+j}`$ is the $`k`$-th difference ($`k = 3`$ in this project): the first difference is the slope, the second the curvature, the third the *change* of curvature. The weights are the deaths because of (4.2): $`\mathrm{Var}(y_x) \approx 1/\mathcal{D}_x`$, so deaths are inverse-variance weights, and ages with many deaths count for more.

The parameter $`\lambda \ge 0`$ sets the trade. In matrix form the second term is $`\lambda\, \mathbf{z}^\top \boldsymbol\Delta^{k\top}\boldsymbol\Delta^{k}\, \mathbf{z}`$; call $`\mathbf{P} = \boldsymbol\Delta^{k\top}\boldsymbol\Delta^{k}`$ the penalty matrix. Setting the gradient of (4.5) to zero, $`-2\mathbf{W}(\mathbf{y} - \mathbf{z}) + 2\lambda \mathbf{P}\mathbf{z} = 0`$, gives a linear system with a closed-form solution:

$$
\left(\mathbf{W} + \lambda \mathbf{P}\right)\hat{\mathbf{z}} = \mathbf{W}\mathbf{y}, \qquad \hat{\mathbf{z}} = \mathbf{S}\,\mathbf{y}, \quad \mathbf{S} = \left(\mathbf{W} + \lambda \mathbf{P}\right)^{-1}\mathbf{W}. \tag{4.6}
$$

The matrix $`\mathbf{S}`$ is the **smoother**: each fitted value is a weighted average of the observed ones (every row of $`\mathbf{S}`$ sums to 1, because a constant is never penalized). The **effective number of parameters** is its trace, the number of free "knobs" the fit really uses:

$$
\mathrm{edf} = \mathrm{tr}(\mathbf{S}). \tag{4.7}
$$

Because $`\mathrm{Var}(\mathbf{y}) \approx \mathbf{W}^{-1}`$, the variance of the fitted log-rates is

$$
\mathrm{Var}(\hat{\mathbf{z}}) = \mathbf{S}\,\mathbf{W}^{-1}\mathbf{S}^\top = \left(\mathbf{W} + \lambda \mathbf{P}\right)^{-1}\mathbf{W}\left(\mathbf{W} + \lambda \mathbf{P}\right)^{-1}. \tag{4.8}
$$

**What $`\lambda`$ does.** The penalty $`\Delta^k z = 0`$ exactly when $`z`$ is a polynomial of degree below $`k`$ in age. So as $`\lambda`$ moves from 0 to infinity the fit moves between two poles:

$$
\lambda \to 0:\ \hat z_x \to y_x\ (\mathrm{edf} \to n), \qquad\qquad \lambda \to \infty:\ \hat z \to \text{a polynomial of degree } k-1\ (\mathrm{edf} \to k). \tag{4.9}
$$

With $`k = 3`$ the limit is a parabola in $`\log m`$ against age; with $`k = 2`$ it is a straight line, which is *exactly* the Gompertz law (section 4.6). A curve already inside that polynomial family is returned untouched, for any $`\lambda`$: smoothing never distorts what is already smooth.

## 4.4 The Poisson P-spline

Whittaker-Henderson has one parameter per age and treats $`\log \hat m`$ as Gaussian, which is a fair approximation only when counts are large. The **P-spline** (Eilers and Marx, 1996) keeps the roughness penalty but fits the Poisson model directly, through a flexible curve built from a modest number of basis functions.

**The curve.** Write $`\log m_x = \sum_{j=1}^{K} \theta_j B_j(x)`$, where $`B_j`$ are cubic **B-splines** on equally spaced knots (40 intervals across ages 1 to 89, so $`K = 43`$). A B-spline is a smooth bump that is non-zero over only four knot intervals, so each coefficient controls the curve locally. B-splines have a property used below: at every age they are non-negative and **add to 1**,

$$
\sum_{j=1}^{K} B_j(x) = 1 \quad \text{for every } x, \qquad \text{so } \mathbf{B}\mathbf{1}_K = \mathbf{1}_n. \tag{4.10}
$$

**The penalized likelihood.** With $`\eta = \mathbf{B}\theta`$ and expected deaths $`\mu^{*}_x = \mathcal{E}_x e^{\eta_x}`$ (the exposure is an *offset*), the Poisson log-likelihood is $`\sum_x [\mathcal{D}_x \eta_x - \mu^{*}_x]`$ plus a constant. Penalize the roughness of the **coefficients** with second differences ($`\mathbf{P} = \boldsymbol\Delta^{2\top}\boldsymbol\Delta^{2}`$):

$$
\ell_p(\theta) = \sum_x \left[\mathcal{D}_x \eta_x - \mu_x^{*}\right] - \frac{\lambda}{2}\,\theta^\top \mathbf{P}\,\theta. \tag{4.11}
$$

**Fitting.** Setting the gradient to zero gives the **score equation**

$$
\mathbf{B}^\top\left(\mathcal{D} - \mu^{*}\right) = \lambda\,\mathbf{P}\theta. \tag{4.12}
$$

It is not linear in $`\theta`$ (since $`\mu^{*}`$ depends on it), but Newton's method on (4.11) has a neat form. The Hessian is $`-(\mathbf{B}^\top \mathbf{W}\mathbf{B} + \lambda \mathbf{P})`$ with $`\mathbf{W} = \mathrm{diag}(\mu^{*})`$; one Newton step $`\theta \mapsto \theta + (\mathbf{B}^\top \mathbf{W}\mathbf{B} + \lambda\mathbf{P})^{-1}[\mathbf{B}^\top(\mathcal{D} - \mu^{*}) - \lambda\mathbf{P}\theta]`$ simplifies to a **weighted penalized least-squares** problem:

$$
\left(\mathbf{B}^\top \mathbf{W}\mathbf{B} + \lambda\mathbf{P}\right)\theta_{\text{new}} = \mathbf{B}^\top \mathbf{W}\,\mathbf{u}, \qquad u_x = \eta_x + \frac{\mathcal{D}_x - \mu^{*}_x}{\mu^{*}_x}. \tag{4.13}
$$

($`\mathbf{u}`$ is the *working response*.) Iterating (4.13) until $`\theta`$ stops changing is *iteratively reweighted least squares*. It is the same linear solve as (4.6) with Poisson weights recomputed at each pass, which is why the two smoothers behave alike.

**A conservation law.** Add up the $`K`$ equations in (4.12) (multiply by $`\mathbf{1}_K^\top`$). On the left, $`\mathbf{1}_K^\top \mathbf{B}^\top = (\mathbf{B}\mathbf{1}_K)^\top = \mathbf{1}_n^\top`$ by (4.10). On the right, $`\mathbf{1}_K^\top \mathbf{P}\theta = (\mathbf{P}\mathbf{1}_K)^\top\theta = 0`$, because differences of a constant vanish. Therefore

$$
\sum_x \mu_x^{*} = \sum_x \mathcal{D}_x. \tag{4.14}
$$

**The fitted curve reproduces the total number of deaths exactly**, whatever $`\lambda`$ is. Smoothing moves deaths between ages; it never creates or destroys them. (In the code a tiny ridge, $`10^{-9}\,\mathbf{I}`$, keeps the system invertible, so the identity holds to about one part in a million; the warehouse check asks for 0.1%.)

**Effective parameters and uncertainty.** As in (4.7),

$$
\mathrm{edf} = \mathrm{tr}\!\left[\left(\mathbf{B}^\top \mathbf{W}\mathbf{B} + \lambda\mathbf{P}\right)^{-1}\mathbf{B}^\top \mathbf{W}\mathbf{B}\right], \qquad \mathrm{edf} \to K = 43 \text{ as } \lambda \to 0, \quad \mathrm{edf} \to 2 \text{ as } \lambda \to \infty. \tag{4.15}
$$

(The limit 2 is the dimension of what second differences ignore: a constant and a line, so a Gompertz curve.) The variance of the fitted log-rate at age $`x`$ is approximated by $`v_x = \mathbf{b}_x^\top (\mathbf{B}^\top \mathbf{W}\mathbf{B} + \lambda\mathbf{P})^{-1} \mathbf{b}_x`$, with $`\mathbf{b}_x`$ the row of $`\mathbf{B}`$ at age $`x`$. Because the data are overdispersed, the interval multiplies $`v_x`$ by the dispersion $`\psi`$ of section 4.5 (never below 1):

$$
\left[\, m_x\, e^{-h_x},\; m_x\, e^{+h_x} \,\right], \qquad h_x = z_{0.975}\sqrt{v_x \max(\psi, 1)}. \tag{4.16}
$$

## 4.5 How smooth is smooth enough

Both smoothers need $`\lambda`$. Too small and the curve follows the noise; too large and it flattens real features. The project chooses it by an information criterion, searched over a grid of 61 values of $`\lambda`$ between $`10^{-2}`$ and $`10^{8}`$.

**Akaike's criterion** weighs misfit against complexity: $`\mathrm{AIC} = -2\log L + 2p`$, with $`p`$ the number of parameters, here the effective number $`\mathrm{edf}`$. For a Poisson model $`-2\log L`$ is the deviance (4.3) up to a constant. This works when the data are exactly Poisson. With overdispersion it fails in a particular way: the deviance is *inflated* by extra scatter that no smooth curve can explain, the criterion reads this as "more complexity is needed", and it picks a curve that chases the noise. The remedy is the **quasi-AIC** (Burnham and Anderson, 2002), which divides the deviance by the dispersion $`\psi`$, the factor by which the scatter exceeds Poisson:

$$
\mathrm{QAIC}(\lambda) = \frac{\mathrm{Dev}(\lambda)}{\psi} + 2\,\mathrm{edf}(\lambda), \qquad \hat\lambda = \arg\min_\lambda \mathrm{QAIC}(\lambda). \tag{4.17}
$$

**Estimating $`\psi`$ without a fitted curve.** The dispersion could be estimated from the best fit's own residuals, but that is circular (an over-flexible fit has small residuals and makes $`\psi`$ look like 1, which switches the penalty off). The project instead uses the crude rates' own **higher-order differences**. If $`\log m_x`$ is smooth, its $`k`$-th difference is almost zero, so the $`k`$-th difference of the observed $`\log \mathcal{D}_x`$ is almost pure noise. By (4.2), and since neighbouring ages are independent, that noise has variance $`\sum_{j=0}^{k}\binom{k}{j}^{2} / \mathcal{D}_{x+j}`$. The ratio of observed to expected squared differences estimates the dispersion:

$$
\hat\psi = \max\!\left(1,\ \operatorname*{mean}_x \frac{\left(\Delta^{k}\log \mathcal{D}_x\right)^{2}}{\sum_{j=0}^{k}\binom{k}{j}^{2}/\mathcal{D}_{x+j}}\right), \qquad k = 4. \tag{4.18}
$$

For $`k = 4`$ the coefficients are $`1, -4, 6, -4, 1`$ and $`\sum_j \binom{4}{j}^2 = \binom{8}{4} = 70`$, so with constant counts $`\mathcal{D}`$ the denominator is $`70/\mathcal{D}`$. A value of 1 means the scatter is exactly Poisson; 2 means twice as much as luck explains.

**What it says about the data** (computed from the shipped database, ages 1 to 89, 2020 to 2024, $`k = 4`$):

| | Women | Men |
|---|:-:|:-:|
| Dispersion $`\hat\psi`$ | 1.00 to 1.69 | 1.85 to 3.09 |

Women's rates are close to pure Poisson noise; men's scatter is up to **three times** what sampling alone explains. The estimate is stable for $`k`$ from 3 to 5 (for 2023 men: 2.45, 2.44, 2.43). The tests in `tests/test_graduation.py` guard the behavior that matters: exactly-Gompertz data must select the straight line (2 parameters), and data with a bump must stay flexible.

## 4.6 Two laws and a closure curve

A **law of mortality** describes the whole age pattern with a handful of parameters. Laws are neat, and the project fits two of them to see what a smoother can do that a law cannot.

**Gompertz-Makeham.** The force of mortality is an age-independent part plus an exponential that rises with age:

$$
\mu_x = A + B\,c^{x}, \qquad c > 1. \tag{4.19}
$$

For $`A = 0`$, $`\log\mu_x = \log B + x\log c`$ is a straight line, and the force *doubles every* $`\ln 2/\ln c`$ *years*: 7.27 years for $`c = 1.1`$. This "mortality doubling time" is the reason a Gompertz fit looks like a straight line on the log scale used throughout this handbook. The project fits it from age 35 up, as a baseline.

**Heligman-Pollard** (1980) writes the odds of dying, $`q_x/p_x`$, as a sum of three terms, one for each phase of life:

$$
\frac{q_x}{p_x} = \underbrace{A^{(x+B)^{C}}}_{\text{childhood decline}} \;+\; \underbrace{D\,\exp\!\left[-E\,(\ln x - \ln F)^{2}\right]}_{\text{the young-adult hump}} \;+\; \underbrace{G\,H^{x}}_{\text{Gompertz aging}}. \tag{4.20}
$$

The first term falls steeply from infancy (with $`A < 1`$, $`A^{(x+B)^C}`$ shrinks as $`x`$ grows); the second is a bump centred at age $`F`$ with width governed by $`E`$ (accidents and violence in young adults); the third is a Gompertz term. That is eight parameters, $`A`$ to $`H`$. The code turns the odds into a probability $`q = \text{odds}/(1+\text{odds})`$ and then into a central rate with $`m = q/(1 - q/2)`$, the inverse of (4.24).

**Kannisto.** For the oldest ages the data are unreliable (section 4.8), and a Gompertz curve is the wrong shape there: it keeps accelerating, without limit. Observed mortality at extreme ages *decelerates*. The logistic form of Thatcher, Kannisto and Vaupel (1998), anchored at age 80, has linear **log-odds** and so cannot exceed 1:

$$
\frac{m_x}{1 - m_x} = a\,e^{\,b(x - 80)} \quad\Longleftrightarrow\quad m_x = \frac{a\,e^{\,b(x-80)}}{1 + a\,e^{\,b(x-80)}}. \tag{4.21}
$$

**Fitting a law.** Each law is fitted by maximum Poisson likelihood, which is the same as minimising the deviance (4.3), which is a sum of squares of **signed deviance residuals** $`r_x = \operatorname{sign}(\mathcal{D}_x - \mu_x^{*})\sqrt{\mathrm{dev}_x}`$:

$$
\hat p = \arg\min_p \sum_x r_x(p)^2 = \arg\min_p \mathrm{Dev}(p). \tag{4.22}
$$

Written as a least-squares problem, a solver that rescales each parameter by its own sensitivity (the Jacobian) can handle parameters whose effects differ by orders of magnitude, such as the childhood and old-age terms of (4.20). A plain likelihood optimizer stopped early and made Heligman-Pollard look about a quarter worse than it should; trying more starting points did not reveal it, so a test now recovers a known Heligman-Pollard curve from simulated data. Laws with several local optima are fitted from six starting points, and the lowest deviance wins.

## 4.7 Tests of fit

A graduated curve is judged by what is left over, the standardized residuals $`z_x`$ of (4.4). The project stores, for every year, sex and method:

| Test | Statistic | What a bad fit looks like |
|---|---|---|
| **Chi-square** | $`\chi^2 = \sum_x z_x^2`$ against $`n - \mathrm{edf}`$ degrees of freedom; $`\chi^2/(n - \mathrm{edf})`$ is the dispersion of the *fit* | Dispersion far above 1 |
| **Signs** | Number of positive residuals, against a binomial law with $`n`$ trials and probability $`\tfrac12`$ | Too many of one sign: the curve is biased up or down |
| **Runs** | Number of runs $`R`$ of same-sign residuals, against mean $`\frac{2 n_+ n_-}{n} + 1`$ and variance $`\frac{2 n_+ n_-(2 n_+ n_- - n)}{n^2(n-1)}`$ | Too few runs: long stretches where the curve is on one side of the data |
| **Serial correlation** | $`r_1 = \dfrac{\sum_x z_x z_{x+1}}{\sqrt{\sum_x z_x^2 \sum_x z_{x+1}^2}}`$, tested with $`2\,\Phi(-\lvert r_1\rvert\sqrt{n})`$ | Large $`\lvert r_1\rvert`$: neighbouring residuals move together (positive) or alternate (negative) |
| **Cumulative deviation** | $`\sum_x(\mathcal{D}_x - \mu_x^{*}) / \sqrt{\sum_x \mu_x^{*}}`$ | Far from 0: the total deaths are not reproduced |
| **Share beyond 2** | Fraction of $`\lvert z_x\rvert > 2`$ | Far above 4.55% |
| **Smoothness** | Mean $`\lvert \Delta^3 \log m_x \rvert`$ | A big number: the curve is rough |

> [!IMPORTANT]
> With hundreds of thousands of deaths, **every smooth curve fails the chi-square and runs tests**, because the data contain real irregularities (such as the age-heaping in section 4.10) that no smooth curve follows. A p-value cannot tell a good fit from a bad one here; the *size* of the misfit can. The measures that carry the argument are the dispersion of the fit and the share of residuals beyond 2.

## 4.8 Closing the table at the oldest ages

Above about age 88 the crude data stop being trustworthy (section 4.12), so the table is assembled from three pieces:

1. **Age 0** keeps its crude rate. An infant's first year has its own steep shape (tens of thousands of deaths, many of them in the first weeks), which neither smoother could follow. The rate is converted to a probability with an infant-specific separation factor (chapter 5).
2. **Ages 1 to 89** come from the P-spline.
3. **Ages 75 to 110** are carried by the Kannisto curve (4.21), fitted to ages 75 to 89 by (4.22).

Between ages 84 and 90 the spline hands over to Kannisto with a **weight on the spline** that falls linearly, and the two are mixed on the log scale, so there is no jump:

$$
w_x = \min\!\left(1,\ \max\!\left(0,\ \frac{90 - x}{6}\right)\right), \qquad \log m_x = w_x \log m_x^{\text{spline}} + (1 - w_x)\log m_x^{\text{Kannisto}}. \tag{4.23}
$$

At $`x = 87`$, $`w = \tfrac12`$ and $`m_x`$ is the geometric mean of the two curves.

**Rate to probability.** Above infancy the project assumes deaths are spread evenly through the year, so the separation factor is $`\phi = \tfrac12`$ and equation (5.5) of chapter 5 becomes

$$
q_x = \frac{m_x}{1 + \tfrac12\, m_x}, \qquad q_{110} = 1. \tag{4.24}
$$

Its inverse, $`m = q / (1 - q/2)`$, is what turns Heligman-Pollard's $`q`$ into a central rate in section 4.6. A useful consequence: when chapter 5 recovers the separation factor from the graduated $`m_x`$ and $`q_x`$, it finds exactly $`\phi_x = \tfrac12`$ at every age from 1 up to $`\omega - 1`$.

**The sex floor.** In Mexico's data women's crude rates overtake men's above about age 88, which no population has shown and which points to **age exaggeration** among the oldest men (people recorded as older than they are, which inflates their exposure and deflates their rate). The closure therefore never lets men's rates fall below women's from age 84:

$$
m^{M}_x \leftarrow \max\!\left(m^{M}_x,\ m^{F}_x\right) \quad \text{for } x \ge 84, \tag{4.25}
$$

and marks the changed ages with `sex_floor = 1`. This is a **floor, not an estimate**: it makes male old-age rates a lower bound.

## 4.9 A fit you can check by hand

Three ages, four deaths each, and exposures of 400, 100 and 400 person-years. The crude rates are $`0.01,\ 0.04,\ 0.01`$: the middle age looks four times riskier, which is exactly the kind of noise to smooth. Use Whittaker-Henderson with first differences ($`k = 1`$, the penalty pulls the fit toward a constant) and $`\lambda = 4`$.

**Setting up.** $`w_x = \mathcal{D}_x = 4`$ at every age, so $`\mathbf{W} = 4\mathbf{I}`$ and $`\lambda \mathbf{P} = 4\mathbf{P}`$, with

$$
\mathbf{P} = \boldsymbol\Delta^{1\top}\boldsymbol\Delta^{1} = \begin{pmatrix} 1 & -1 & 0 \\ -1 & 2 & -1 \\ 0 & -1 & 1 \end{pmatrix}.
$$

Dividing (4.6) through by 4, the system is $`(\mathbf{I} + \mathbf{P})\,\hat{\mathbf{z}} = \mathbf{y}`$. Subtract the constant $`\log 0.01`$ from every value (constants are not penalized), so that $`\mathbf{y} = (0,\ L,\ 0)`$ with $`L = \log 4 = 1.3863`$.

**Solving.** By symmetry $`\hat z_1 = \hat z_3 = a`$ and $`\hat z_2 = b`$. The first row of $`(\mathbf{I} + \mathbf{P})\hat{\mathbf{z}} = \mathbf{y}`$ is $`2a - b = 0`$, so $`b = 2a`$. The second row is $`-2a + 3b = L`$, so $`-2a + 6a = L`$ and $`a = L/4`$, $`b = L/2`$. Adding back $`\log 0.01`$:

$$
\hat m = 0.01 \times \left(4^{1/4},\ 4^{1/2},\ 4^{1/4}\right) = (0.014142,\ 0.020000,\ 0.014142).
$$

| Age | Deaths | Exposure | Crude $`\hat m`$ | Graduated $`m`$ | Fitted deaths $`\mu^{*}`$ | $`z`$ (4.4) |
|:-:|:-:|--:|--:|--:|--:|--:|
| 1 | 4 | 400 | 0.01000 | 0.01414 | 5.657 | -0.697 |
| 2 | 4 | 100 | 0.04000 | 0.02000 | 2.000 | +1.414 |
| 3 | 4 | 400 | 0.01000 | 0.01414 | 5.657 | -0.697 |

The curve has pulled the outer ages up and the middle one down, to a compromise between "all three the same" and "each as observed".

**Effective parameters.** $`\mathbf{S} = (\mathbf{I} + \mathbf{P})^{-1}`$ has diagonal $`(\tfrac58,\ \tfrac12,\ \tfrac58)`$, so by (4.7) $`\mathrm{edf} = \tfrac{14}{8} = 1.75`$: between 1 (a constant) and 3 (the crude rates).

**Variance.** By (4.8) the variance of the fitted log-rates is $`(0.1172,\ 0.0938,\ 0.1172)`$, against $`1/\mathcal{D} = 0.25`$ for each crude rate: smoothing has more than halved the uncertainty, the benefit of borrowing strength between ages.

**Misfit.** The expected deaths add to $`8\sqrt2 + 2 = 13.31`$ against 12 observed. The deviance (4.3) is

$$
2\Big[\textstyle\sum \mathcal{D}\log(\mathcal{D}/\mu^{*}) - \sum(\mathcal{D} - \mu^{*})\Big] = 2\big[0 - (12 - 13.314)\big] = 16\sqrt2 - 20 = 2.627,
$$

(the logarithm terms cancel exactly in this example). The chi-square is $`\sum z_x^2 = 2.971`$ on $`3 - 1.75 = 1.25`$ degrees of freedom, a dispersion of 2.38. The signs run $`-,+,-`$, so there are three runs and the serial correlation (section 4.7) is $`-0.793`$; no residual passes 2, so the share beyond 2 is 0.

Run it yourself:

```python
import numpy as np
from mortality.graduation import whittaker_henderson

fit = whittaker_henderson(
    np.array([1, 2, 3]), np.array([4.0, 4, 4]), np.array([400.0, 100, 400]), order=1, lam=4.0
)
print(fit.mx, fit.edf, fit.deviance)  # [0.014142 0.02 0.014142]  1.75  2.627
```

## 4.10 Validation

Five independent checks stand behind the code; the first two run in the test-suite on every commit.

1. **The identities of this chapter** are tested numerically in `tests/test_handbook_graduation.py`: the normal equations, the score equation at the fitted P-spline, the conservation law (4.14), the limits of the effective parameters, the exact recovery of curves inside the penalty's null space, the dispersion estimator on Poisson and on overdispersed counts (unbiased: 3.07 on average for a true 3), the runs-test mean and variance against an exhaustive count of arrangements, and the hand-solved example above.
2. **Planted truth.** `tests/test_graduation.py` generates Poisson counts from known Gompertz and Heligman-Pollard curves and checks that each method recovers them, including the choice of $`\lambda`$ (a straight line for exact Gompertz data, flexibility when there is a bump).
3. **The data, 2023.** The quantities quoted in this chapter are tested against the shipped database:

| 2023 | Women | Men |
|---|--:|--:|
| P-spline deviance | 98.9 | 129.4 |
| Heligman-Pollard deviance | 872.9 | 1,123.9 |
| Ratio | **8.8** | **8.7** |
| P-spline effective parameters | 33.1 | 36.4 |
| P-spline residuals beyond 2 (benchmark 4.55%) | 4.5% | 10.1% |

Averaged over the five years the Heligman-Pollard deviance is 1,159 (women) and 2,052 (men) against 77 and 122 for the P-spline: 15 to 17 times worse. Across all years the P-spline uses 33 to 39 effective parameters, Whittaker-Henderson 31 to 43, Heligman-Pollard 8 and Gompertz-Makeham 3. Heligman-Pollard leaves 44 to 73% of its residuals beyond 2: it cannot follow the data.

4. **What the residuals found.** Standardized residuals of the smooth curve spike at ages ending in 0 and 5 for men (**digit preference**: ages reported rounded). Measured against the fit over ages 25 to 70, men's deaths at those ages exceed the curve by 1.25 to 2.46% in every year from 2020 to 2024 and fall short elsewhere by 0.3 to 0.7%. The Whipple index of [chapter 2](02-data-exposure-quality.md#22-do-certificates-round-ages-heaping-indices) averages over both sexes and a wide age range and calls the data "highly accurate" (98 to 101), so it cannot see a 2% effect in one sex. It explains why the serial correlation of the residuals is negative (about $`-0.45`$ to $`-0.53`$ for the smoothers in 2023) and is the reason a smooth curve is the right tool: it ignores the heaping instead of chasing it.
5. **Downstream.** The graduated table feeds chapter 5, where the life table built on it reproduces the Human Mortality Database's life expectancy to within 0.007 years when fed HMD's own rates, and CONAPO's within 0.7 years in 2022 to 2024.

## 4.11 Code map

| Formula | Function (`src/mortality/graduation.py`) | Checked by (`tests/test_handbook_graduation.py`) |
|---|---|---|
| (4.2) | `noise_dispersion` (its denominator) | `test_log_of_a_poisson_count_has_variance_one_over_the_mean` |
| (4.3), (4.4) | `poisson_deviance`, `fit_tests` | `test_deviance_is_twice_the_log_likelihood_gap_to_the_saturated_model` |
| (4.5), (4.6), (4.7), (4.8) | `whittaker_henderson` | `test_whittaker_henderson_solves_the_normal_equations`, `..._toy_matches_the_handbook` |
| (4.9) | `whittaker_henderson`, `difference_penalty` | `test_whittaker_henderson_limits_of_the_smoothing_parameter`, `test_a_curve_in_the_null_space_is_recovered_for_any_smoothing` |
| (4.10) | `bspline_basis` | `test_graduation.py::test_bspline_basis_is_a_partition_of_unity` |
| (4.11), (4.12), (4.13) | `pspline`, `_pspline_solve` | `test_pspline_satisfies_the_penalized_score_equation` |
| (4.14) | `pspline` | `test_pspline_reproduces_total_deaths` |
| (4.15), (4.16) | `pspline`, `Graduation.interval` | `test_pspline_effective_parameters_run_from_the_basis_size_down_to_two`, `test_pspline_interval_is_the_log_scale_band_scaled_by_the_dispersion` |
| (4.17), (4.18) | `select_lambda`, `noise_dispersion` | `test_quasi_aic_is_deviance_over_dispersion_plus_twice_the_parameters`, `test_dispersion_is_one_for_poisson_noise_and_recovers_extra_scatter` |
| (4.19), (4.20), (4.21) | `gompertz_makeham`, `heligman_pollard`, `kannisto` | `test_gompertz_doubles_...`, `test_heligman_pollard_is_defined_through_the_odds`, `test_kannisto_has_linear_log_odds_and_stays_below_one` |
| (4.22) | `fit_parametric` | `test_a_law_is_fitted_by_least_squares_on_deviance_residuals` |
| Section 4.7 | `fit_tests` | `test_fit_tests_on_the_toy_example`, `test_runs_test_formulas_match_a_direct_count`, `test_a_perfect_fit_puts_4_point_55_percent_of_residuals_beyond_two` |
| (4.23), (4.24) | `blend_weight`, `assemble_table`, `mx_to_q` | `test_blend_weights_and_the_geometric_mean`, `test_q_from_m_is_the_separation_factor_formula_with_one_half`, `test_the_assembled_table_runs_from_0_to_110_and_closes_at_one` |
| (4.25) | `enforce_sex_order` | `test_the_sex_floor_lifts_male_rates_to_female_rates_and_marks_them` |
| Section 4.10, table | `build_tables` (the warehouse) | `test_chapter_numbers_match_the_database` |

## 4.12 Limits

- **One year at a time.** Each year and sex is graduated alone: no strength is borrowed across years. The 2020 to 2022 tables carry the pandemic and are not reference tables; 2023 is. Projection (chapter 6) is where time enters.
- **Single ages exist only from 2020.** There is no graduated 2019 baseline from single-age data.
- **The dispersion estimate (4.18) assumes** a smooth underlying curve and independent errors across ages. Digit preference breaks the second assumption mildly (section 4.10); if anything it inflates the estimate a little, which makes the chosen curve slightly smoother.
- **The intervals (4.16) are approximate** (they use a Bayesian-style variance for the penalized fit, scaled by $`\psi`$) and exist only for the P-spline ages up to 84. The Kannisto closure and the two laws have none.
- **Above about age 88 the data are not credible.** Women overtake men, which no population shows, and men's crude rates flatten near 0.19 where the USA and Japan keep rising to 0.4 and above. The sex floor (4.25) is a floor and not an estimate, so male rates above 90 are a **lower bound** until a better exposure series exists (census age checks, pension records).
- **Graduation cannot repair biased exposure.** It smooths noise; it does not know that an exposure is wrong. At the oldest ages that is where most of the uncertainty lies.
- **$`q`$ from $`m`$ with $`\phi = \tfrac12`$** (4.24) is an approximation above infancy; the life tables of chapter 5 can refine it with the shape of the graduated rates.

## References

- Whittaker, E. T. (1922). On a new method of graduation. *Proceedings of the Edinburgh Mathematical Society* 41, 63-75. Henderson, R. (1924). A new method of graduation. *Transactions of the Actuarial Society of America* 25, 29-40.
- Eilers, P. H. C. and Marx, B. D. (1996). Flexible smoothing with B-splines and penalties. *Statistical Science* 11(2), 89-121.
- Currie, I. D., Durban, M. and Eilers, P. H. C. (2004). Smoothing and forecasting mortality rates. *Stat. Model.* 4(4), 279-298.
- Heligman, L. and Pollard, J. H. (1980). The age pattern of mortality. *Journal of the Institute of Actuaries* 107(1), 49-80.
- Forfar, D. O., McCutcheon, J. J. and Wilkie, A. D. (1988). On graduation by mathematical formula. *Journal of the Institute of Actuaries* 115(1), 1-135. (The graduation tests of section 4.7.)
- Thatcher, A. R., Kannisto, V. and Vaupel, J. W. (1998). *The Force of Mortality at Ages 80 to 120*. Odense University Press.
- Burnham, K. P. and Anderson, D. R. (2002). *Model Selection and Multimodel Inference*, 2nd ed. Springer. (Quasi-AIC.)
- Preston, S. H., Heuveline, P. and Guillot, M. (2001). *Demography: Measuring and Modeling Population Processes*. Blackwell.
