'use strict';
const $ = id => document.getElementById(id);
const money = n => new Intl.NumberFormat('en-AU', {
  style: 'currency', currency: 'AUD',
  minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
  maximumFractionDigits: 2
}).format(n);
const displayAddress = address => address.toLowerCase().replace(/\b[a-z]/g, c => c.toUpperCase());
let meta, selected = null, parking = true;
let searchSequence = 0, detailSequence = 0, timer;
let currentPage = 1, pageCount = 1;

async function api(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Unable to load data.');
  return data;
}
function showError(error) {
  $('error').textContent = error.message || String(error);
  $('error').hidden = false;
}
function clearSelection() {
  detailSequence++;
  selected = null;
  $('property').hidden = true;
  $('empty').hidden = false;
  $('detailStatus').hidden = true;
  $('detail').setAttribute('aria-busy', 'false');
}
function setScenario(value) {
  parking = value;
  $('with').setAttribute('aria-pressed', String(value));
  $('without').setAttribute('aria-pressed', String(!value));
  if (!selected) return;
  $('price').textContent = money(value ? selected.with_parking : selected.without_parking);
  $('scenarioLabel').textContent = value ? 'WITH AT LEAST ONE CAR SPACE' : 'WITHOUT A CAR SPACE';
}
function attribute(label, value) {
  if (value === null) return label === 'Floor' ? 'Floor unknown' : `${label} unknown`;
  if (label === 'Floor') return `Floor ${value}`;
  return `${value} ${label === 'Bedrooms' ? (value === 1 ? 'bedroom' : 'bedrooms') : (value === 1 ? 'bathroom' : 'bathrooms')}`;
}
async function choose(id) {
  const ticket = ++detailSequence;
  $('detail').setAttribute('aria-busy', 'true');
  $('detailStatus').textContent = 'Loading the selected flat…';
  $('detailStatus').hidden = false;
  $('property').hidden = true;
  $('empty').hidden = true;
  try {
    const record = await api('/api/property?id=' + encodeURIComponent(id));
    if (ticket !== detailSequence) return;
    selected = record;
    $('error').hidden = true;
    $('property').hidden = false;
    $('location').textContent = record.suburb + (meta.demo ? ' · FICTIONAL EXAMPLE' : '');
    $('address').textContent = displayAddress(record.address);
    $('attributes').replaceChildren();
    for (const [label, value] of [['Bedrooms', record.bedrooms], ['Bathrooms', record.bathrooms], ['Floor', record.floor_level]]) {
      const tag = document.createElement('span');
      tag.textContent = attribute(label, value);
      $('attributes').append(tag);
    }
    $('yesPrice').textContent = money(record.with_parking);
    $('noPrice').textContent = money(record.without_parking);
    const premium = record.with_parking - record.without_parking;
    $('premium').textContent = (premium > 0 ? '+' : '') + money(premium) + '/wk';
    $('annualPremium').textContent = money(premium * 52) + ' over 52 weeks';
    $('zeroPremium').hidden = premium !== 0;
    $('gnaf').textContent = record.gnaf_id;
    $('recordedParking').textContent = record.car_space === null ? 'Unknown' : record.car_space === 1 ? 'At least one car space' : 'No car space';
    $('source').textContent = meta.source;
    // Start with the known recorded scenario; unknown records start with parking.
    setScenario(record.car_space !== 0);
    document.querySelectorAll('.result').forEach(button => {
      const active = button.dataset.id === id;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    if (window.innerWidth < 850) {
      $('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (error) {
    if (ticket === detailSequence) {
      selected = null;
      $('empty').hidden = false;
      showError(error);
    }
  } finally {
    if (ticket === detailSequence) {
      $('detailStatus').hidden = true;
      $('detail').setAttribute('aria-busy', 'false');
    }
  }
}
function lockResults() {
  $('results').setAttribute('aria-busy', 'true');
  document.querySelectorAll('.result').forEach(button => { button.disabled = true; });
  $('previous').disabled = true;
  $('next').disabled = true;
}
async function search(page = 1) {
  clearTimeout(timer);
  const ticket = ++searchSequence;
  clearSelection();
  lockResults();
  $('count').textContent = 'Searching…';
  try {
    const query = new URLSearchParams({
      q: $('search').value, suburb: $('suburb').value,
      beds: $('beds').value, page: String(page)
    });
    const result = await api('/api/search?' + query);
    if (ticket !== searchSequence) return;
    currentPage = result.page;
    pageCount = result.pages;
    $('error').hidden = true;
    $('results').replaceChildren();
    $('results').scrollTop = 0;
    $('count').textContent = result.total ? `${result.start.toLocaleString()}–${result.end.toLocaleString()} of ${result.total.toLocaleString()} matching flats` : 'No matching flats';
    $('pagination').hidden = result.pages <= 1;
    $('pageLabel').textContent = `${currentPage} / ${pageCount}`;
    $('previous').disabled = currentPage <= 1;
    $('next').disabled = currentPage >= pageCount;
    if (!result.items.length) {
      const empty = document.createElement('p');
      empty.className = 'no-results';
      empty.textContent = 'Try a shorter street name or clear a filter. Search words can match the address, suburb or G-NAF ID.';
      $('results').append(empty);
    }
    for (const item of result.items) {
      const button = document.createElement('button');
      button.className = 'result';
      button.dataset.id = item.gnaf_id;
      button.setAttribute('aria-pressed', 'false');
      const title = document.createElement('strong');
      title.textContent = displayAddress(item.address);
      const description = document.createElement('span');
      description.textContent = item.suburb + ' · ' + (item.bedrooms === null ? 'Bedrooms unknown' : item.bedrooms + ' bed') + ' · ' + (item.bathrooms === null ? 'Bathrooms unknown' : item.bathrooms + ' bath');
      button.append(title, description);
      button.addEventListener('click', () => choose(item.gnaf_id));
      $('results').append(button);
    }
  } catch (error) {
    if (ticket === searchSequence) {
      $('count').textContent = 'Search unavailable';
      $('results').replaceChildren();
      $('pagination').hidden = true;
      showError(error);
    }
  } finally {
    if (ticket === searchSequence) $('results').setAttribute('aria-busy', 'false');
  }
}
$('search').addEventListener('input', () => {
  searchSequence++;
  clearTimeout(timer);
  clearSelection();
  lockResults();
  $('count').textContent = 'Searching…';
  timer = setTimeout(() => search(1), 180);
});
for (const id of ['suburb', 'beds']) $(id).addEventListener('change', () => search(1));
$('clear').addEventListener('click', () => {
  $('search').value = ''; $('suburb').value = ''; $('beds').value = '';
  search(1);
  $('search').focus();
});
$('previous').addEventListener('click', () => search(currentPage - 1));
$('next').addEventListener('click', () => search(currentPage + 1));
$('with').addEventListener('click', () => setScenario(true));
$('without').addEventListener('click', () => setScenario(false));
document.addEventListener('keydown', event => {
  if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    event.preventDefault(); $('search').focus();
  }
});
(async () => {
  try {
    meta = await api('/api/meta');
    if (meta.metrics) {
      $('modelError').textContent = '$' + meta.metrics.median_absolute_error.toFixed(2);
      $('modelWithin').textContent = meta.metrics.within_100_pct.toFixed(2) + '%';
      $('modelR2').textContent = meta.metrics.r_squared.toFixed(3);
      $('modelN').textContent = 'R² on ' + meta.metrics.n.toLocaleString() + ' adverts';
      $('modelCheckLabel').textContent = 'May–July 2026 · ' + meta.metrics.n.toLocaleString() + ' adverts. Retrospective check; individual estimates may miss by more.';
    } else {
      $('modelCheckLabel').textContent = 'No verified evaluation metadata for this prediction file.';
    }
    $('coverage').textContent = meta.count.toLocaleString() + (meta.demo ? ' fictional demo flats' : ' flats · two scenarios each');
    $('demoNotice').hidden = !meta.demo;
    $('modeLabel').textContent = meta.demo ? '● Fictional demo' : '● Private local view';
    $('reportLink').hidden = !meta.report_available;
    for (const name of meta.suburbs) {
      const option = document.createElement('option');
      option.value = name; option.textContent = name;
      $('suburb').append(option);
    }
    await search(1);
  } catch (error) {
    $('coverage').textContent = 'Unable to load flats';
    $('count').textContent = 'Search unavailable';
    showError(error);
  }
})();
