function fetchStockMarketStatus() {
  fetch("/api/stock_status/")
    .then(response => response.json())
    .then(data => {
      const tableBody = document.querySelector('.list3 tbody');
      tableBody.innerHTML = ''; // Wyczyść tabelę

      data.forEach((stock, index) => {
        const row = `
          <tr>
            <td>${index + 1}</td>
            <td>${stock.name}</td>
            <td class="${stock.css_class}">${stock.status}</td>
            <td>${stock.time_to_open}</td>
          </tr>
        `;
        tableBody.innerHTML += row;
      });
    })
    .catch(error => {
      console.error("Error fetching stock market status:", error);
    });
}

// Odświeżanie co 60 sekund
setInterval(fetchStockMarketStatus, 1000);
fetchStockMarketStatus();






let suggestionsBox = null;

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('symbol-input');
  suggestionsBox = document.createElement('div');
  suggestionsBox.style.position = 'absolute';
  suggestionsBox.style.background = '#fff';
  suggestionsBox.style.border = '1px solid #ccc';
  suggestionsBox.style.width = input.offsetWidth + 'px';
  suggestionsBox.style.zIndex = 9999;
  input.parentElement.appendChild(suggestionsBox);
  suggestionsBox.style.display = 'none';

  input.addEventListener('input', () => {
    const query = input.value.trim();
    if (query.length > 0) {
      fetch(`/search_instruments/?q=${query}`)
        .then(res => res.json())
        .then(data => {
          suggestionsBox.innerHTML = '';
          if (data.length > 0) {
            data.forEach(item => {
              const div = document.createElement('div');
              div.textContent = item.symbol;
              div.style.padding = '5px';
              div.style.cursor = 'pointer';
              div.addEventListener('click', () => {
                input.value = item.symbol;
                suggestionsBox.style.display = 'none';
              });
              suggestionsBox.appendChild(div);
            });
            suggestionsBox.style.display = 'block';
          } else {
            suggestionsBox.style.display = 'none';
          }
        });
    } else {
      suggestionsBox.style.display = 'none';
    }
  });

  document.getElementById('search-icon').addEventListener('click', () => {
    const symbol = input.value.trim();
    if (symbol) {
      loadInstrumentPrice(symbol);
    }
  });

  // Domyślnie ładujemy US500
  loadInstrumentPrice('US500');
});

function loadInstrumentPrice(symbol) {
  fetch(`/instrument_price/?symbol=${symbol}`)
    .then(res => res.json())
    .then(data => {
      // Załóżmy, że data={ask:1.2345, bid:1.2342}
      const documentsSection = document.querySelector('.list2');
      if (documentsSection) {
        documentsSection.innerHTML = `
          <div class="row">
            <h4>${symbol} Price</h4>
          </div>
          <div style="background:#fff;padding:1rem;border-radius:10px;">
            <p>Ask: ${data.ask}</p>
            <p>Bid: ${data.bid}</p>
          </div>
        `;
      }
    })
    .catch(err => console.error(err));
}

function updateUTCTime() {
  const utcTimeElement = document.getElementById('utc-time');
  if (utcTimeElement) {
    const now = new Date();
    const utcTime = now.toISOString().split('T')[1].split('.')[0]; // Pobierz HH:MM:SS z czasu UTC
    utcTimeElement.textContent = `UTC: ${utcTime}`;
  }
}

// Aktualizuj czas co sekundę
setInterval(updateUTCTime, 1000);
updateUTCTime();

