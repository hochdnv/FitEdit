/* Garmin Connect panel: sign in, list recent activities and download FIT files. */

export function initGarmin({ api, toast, esc, formatDistance, formatDuration, onDownloaded }) {
  const el = (id) => document.getElementById(id);
  let activities = [];
  let existing = new Set();
  let saved = null;

  async function loadConfig() {
    try {
      const cfg = await api('/api/config');
      saved = cfg.garmin;
      el('gcEmail').value = saved.email || '';
      el('gcRemember').checked = saved.remember;
      el('gcPassword').placeholder = saved.hasPassword
        ? 'Password (saved \u2014 leave empty to reuse)' : 'Password';
      el('gcConfigNote').innerHTML = saved.hasPassword
        ? `Stored in ${esc(cfg.file)}, ${saved.encrypted
          ? 'encrypted with Windows DPAPI for your user account'
          : '<b>not encrypted</b> on this platform'}.`
        : `Settings are kept in ${esc(cfg.file)}.`;
    } catch { /* config is optional */ }
  }

  function show(id, on) { el(id).hidden = !on; }

  function setStatus(message, isError = false) {
    const box = el('garminStatus');
    box.innerHTML = message;
    box.classList.toggle('error-text', isError);
  }

  async function refresh() {
    let status;
    try {
      status = await api('/api/garmin/status');
    } catch (err) {
      return setStatus(esc(err.message), true);
    }
    const usable = status.enabled && status.installed;
    show('garminLogin', usable && !status.loggedIn && !status.mfaPending);
    show('garminMfa', usable && status.mfaPending);
    show('garminBrowse', usable && status.loggedIn);

    if (!usable) {
      return setStatus(`${esc(status.hint || 'Garmin Connect is not available.')}`
        + '<br>The rest of the application works without it.');
    }
    if (status.loggedIn) {
      setStatus(`Signed in \u2014 session tokens are cached in ${esc(status.tokenStore)}.`);
      return loadActivities();
    }
    if (status.mfaPending) return setStatus('Enter the verification code Garmin just sent.');
    await loadConfig();
    setStatus('Sign in to Garmin Connect. Your password is sent only to this local '
      + 'server and only the resulting session token is cached, unless you tick '
      + '"remember on this computer".');
  }

  /** Availability check that never contacts Garmin. */
  async function probe() {
    let available = false;
    try {
      const status = await api('/api/garmin/status?probe=1');
      available = Boolean(status.enabled && status.installed);
    } catch { /* keep the button, the dialog explains the problem */ }
    el('garmin').classList.toggle('unavailable', !available);
    el('garmin').title = available
      ? 'Download activities from Garmin Connect'
      : 'Garmin Connect integration is not set up \u2014 click for details';
  }

  async function loadActivities() {
    el('gcList').innerHTML = '<p class="hint">Loading activities\u2026</p>';
    try {
      const days = el('gcDays').value;
      const result = await api(`/api/garmin/activities?days=${encodeURIComponent(days)}`);
      activities = result.activities || [];
      existing = new Set(result.existing || []);
      renderActivities();
    } catch (err) {
      el('gcList').innerHTML = '';
      setStatus(esc(err.message), true);
    }
  }

  function renderActivities() {
    if (!activities.length) {
      el('gcList').innerHTML = '<p class="hint">No activities in this period.</p>';
      el('gcInfo').textContent = '';
      return;
    }
    const rows = activities.map((a) => {
      const onDisk = existing.has(`${a.id}_ACTIVITY.fit`);
      return `<tr>`
        + `<td><input type="checkbox" data-id="${esc(a.id)}"></td>`
        + `<td>${esc((a.start || '').replace('T', ' ').slice(0, 16))}</td>`
        + `<td>${esc(a.name)}</td>`
        + `<td class="muted">${esc(a.type)}</td>`
        + `<td class="num">${a.distance ? esc(formatDistance(a.distance)) : ''}</td>`
        + `<td class="num">${a.duration ? esc(formatDuration(a.duration)) : ''}</td>`
        + `<td class="muted">${onDisk ? 'on disk' : ''}</td>`
        + `</tr>`;
    }).join('');
    el('gcList').innerHTML = '<table class="gc-table"><thead><tr>'
      + '<th><input type="checkbox" id="gcAll" title="Select all"></th>'
      + '<th>Start</th><th>Name</th><th>Type</th><th>Distance</th><th>Duration</th><th></th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>';
    el('gcAll').addEventListener('change', (e) => {
      el('gcList').querySelectorAll('tbody input[type="checkbox"]')
        .forEach((box) => { box.checked = e.target.checked; });
    });
    el('gcInfo').textContent = `${activities.length} activities`;
  }

  function selectedIds() {
    const checked = new Set([...el('gcList').querySelectorAll('tbody input:checked')]
      .map((box) => box.dataset.id));
    return activities.filter((a) => checked.has(String(a.id)))
      .map((a) => ({ id: a.id, name: a.name }));
  }

  async function download() {
    const selected = selectedIds();
    if (!selected.length) return setStatus('Select at least one activity first.', true);
    el('gcDownload').disabled = true;
    setStatus(`Downloading ${selected.length} activit`
      + `${selected.length === 1 ? 'y' : 'ies'}\u2026`);
    try {
      const result = await api('/api/garmin/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ activities: selected }),
      });
      const failed = result.failed || [];
      setStatus(`Downloaded ${result.files.length} file(s).`
        + (failed.length ? ` ${failed.length} failed.` : ''));
      if (failed.length) toast(esc(failed[0].error), true);
      if (result.files.length) {
        toast(`Downloaded: ${esc(result.files.join(', '))}`);
        await onDownloaded(result.files);
      }
      existing = new Set([...existing, ...result.files]);
      renderActivities();
    } catch (err) {
      setStatus(esc(err.message), true);
    } finally {
      el('gcDownload').disabled = false;
    }
  }

  el('garmin').addEventListener('click', () => {
    el('garminModal').hidden = false;
    refresh();
  });
  el('garminClose').addEventListener('click', () => { el('garminModal').hidden = true; });
  el('garminModal').addEventListener('click', (e) => {
    if (e.target.id === 'garminModal') el('garminModal').hidden = true;
  });

  el('garminLogin').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = el('gcEmail').value.trim();
    const password = el('gcPassword').value;
    const remember = el('gcRemember').checked;
    el('gcPassword').value = '';
    if (!password && !(saved && saved.hasPassword)) {
      return setStatus('Enter your password.', true);
    }
    setStatus('Signing in\u2026');
    try {
      const result = await api('/api/garmin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, remember }),
      });
      if (result.status === 'mfa_required') {
        show('garminLogin', false);
        show('garminMfa', true);
        setStatus('Enter the verification code Garmin just sent.');
        el('gcMfa').focus();
        return;
      }
      await refresh();
    } catch (err) {
      setStatus(esc(err.message), true);
    }
  });

  el('garminMfa').addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = el('gcMfa').value.trim();
    el('gcMfa').value = '';
    setStatus('Checking the code\u2026');
    try {
      await api('/api/garmin/mfa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      await refresh();
    } catch (err) {
      setStatus(esc(err.message), true);
      show('garminMfa', false);
      show('garminLogin', true);
    }
  });

  el('gcRefresh').addEventListener('click', () => loadActivities());
  el('gcDays').addEventListener('change', () => loadActivities());
  el('gcDownload').addEventListener('click', () => download());
  el('gcLogout').addEventListener('click', async () => {
    try {
      await api('/api/garmin/logout', { method: 'POST' });
    } catch (err) {
      toast(err.message, true);
    }
    activities = [];
    el('gcList').innerHTML = '';
    refresh();
  });

  probe();
}
