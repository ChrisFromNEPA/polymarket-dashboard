// Router + bootstrap only. All rendering lives in js/views/*.
(() => {
  const VIEWS = {
    verdict: VerdictView,
    calibration: CalibrationView,
    decisions: DecisionsView,
    positions: PositionsView,
    resolutions: ResolutionsView,
    viability: ViabilityView,
    integrity: IntegrityView,
  };

  let current = 'verdict';
  let state = null;

  function $(sel) { return document.querySelector(sel); }

  function renderCurrent() {
    const el = document.getElementById('view-' + current);
    if (!el || !state) return;
    try {
      el.innerHTML = VIEWS[current].render(state);
    } catch (e) {
      el.innerHTML = '<div class="banner banner-bad"><strong>Render error</strong>' +
        '<div class="banner-sub">' + Data.esc(e.message || String(e)) + '</div></div>';
      if (window.console) console.error(e);
    }
  }

  function show(name) {
    if (!VIEWS[name]) name = 'verdict';
    current = name;
    document.querySelectorAll('.tab').forEach(t => {
      t.classList.toggle('active', t.getAttribute('data-view') === name);
    });
    document.querySelectorAll('.view').forEach(v => {
      v.classList.toggle('active', v.id === 'view-' + name);
    });
    if (location.hash.slice(1) !== name) history.replaceState(null, '', '#' + name);
    renderCurrent();
  }

  function offlineBanner(d) {
    // Every file failing usually means file:// — fetch() is blocked there.
    const allMissing = d.missing.length === Object.keys(Data.FILES).length;
    if (!allMissing) return;
    const isFile = location.protocol === 'file:';
    const el = document.getElementById('view-verdict');
    if (!el) return;
    el.insertAdjacentHTML('afterbegin',
      '<div class="banner banner-bad"><strong>No agent data could be loaded</strong>' +
      '<div class="banner-sub">' +
      (isFile
        ? 'Opened from the filesystem, so the browser blocks reading state/*.json. ' +
          'Serve over HTTP, or view the deployed site.'
        : 'state/*.json could not be fetched. The agent may not have published yet.') +
      '</div></div>');
  }

  async function boot() {
    document.querySelectorAll('.tab').forEach(t => {
      t.addEventListener('click', () => show(t.getAttribute('data-view')));
    });
    window.addEventListener('hashchange', () => show(location.hash.slice(1)));

    DecisionsView.bind(renderCurrent);
    ResolutionsView.bind(renderCurrent);

    state = await Data.load();
    show(location.hash.slice(1) || 'verdict');
    offlineBanner(state);

    // The publisher and a scheduled Action both write state/, so poll gently.
    setInterval(async () => {
      state = await Data.load(true);
      renderCurrent();
    }, 60000);
  }

  // Belt and braces. A missed boot leaves a blank shell with no explanation,
  // which is indistinguishable from "the agent published nothing" — so try
  // several triggers and let the guard collapse them into one run.
  let booted = false;
  function bootOnce() {
    if (booted) return;
    booted = true;
    boot().catch(e => {
      const el = document.getElementById('view-verdict');
      if (el) {
        el.innerHTML = '<div class="banner banner-bad"><strong>Dashboard failed to start</strong>' +
          '<div class="banner-sub">' + Data.esc(e.message || String(e)) + '</div></div>';
      }
      if (window.console) console.error(e);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootOnce);
  } else {
    bootOnce();
  }
  window.addEventListener('load', bootOnce);
  setTimeout(bootOnce, 1000);
})();
