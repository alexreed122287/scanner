# Feedback → Google Sheet (5-min setup)

The `✉` floating button in the dashboard POSTs feedback to a Google Apps Script Web App, which appends one row per submission to a Google Sheet you control. Share that Sheet with developers — they get an inbox without you opening GitHub issues.

## One-time setup

### 1. Create the Sheet

[sheets.new](https://sheets.new) → name it "Option Panda Feedback" (or whatever). Add a header row in row 1:

```
timestamp | type | subject | body | version | activeTab | userAgent
```

(The script writes columns in this order; the header is for your eyes.)

### 2. Add the Apps Script

In that sheet: **Extensions → Apps Script**. Replace the default code with:

```javascript
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var sheet = SpreadsheetApp.getActiveSheet();
    sheet.appendRow([
      data.submittedAt || new Date().toISOString(),
      data.type || '',
      data.subject || '',
      data.body || '',
      data.version || '',
      data.activeTab || '',
      data.userAgent || ''
    ]);
    return ContentService.createTextOutput(JSON.stringify({ok:true})).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ok:false, error: String(err)})).setMimeType(ContentService.MimeType.JSON);
  }
}
```

Save (give it a name like "Feedback Sink").

### 3. Deploy as Web App

**Deploy → New deployment → ⚙ → Web app**:

- Description: `Feedback webhook v1`
- Execute as: **Me**
- Who has access: **Anyone**  *(required — your dashboard runs in the browser without Google auth)*

Click **Deploy**, authorize when prompted. Copy the **Web app URL** (looks like `https://script.google.com/macros/s/AKfycb.../exec`).

### 4. Paste it into the dashboard

Open the dashboard → **ALERTS tab** → **FEEDBACK WEBHOOK card** → paste the URL → **SAVE**. Click **▶ SEND TEST** to confirm a row appears in the Sheet.

### 5. Share the Sheet

Standard Google Sheets share — give read access (or comment/edit, your call) to whoever you want to triage feedback. They'll see new submissions as rows appear.

## Notes / caveats

- **Updating the script:** if you change the Apps Script later, you need to redeploy (Deploy → Manage deployments → ✎ on the active deployment → New version → Deploy). The URL stays the same.
- **CORS:** the dashboard sends with `mode:'no-cors'` and `Content-Type:'text/plain'` to avoid Apps Script's preflight quirk. You can't read the response status, but Apps Script logs failures in **Executions** (left sidebar in the script editor) if rows aren't landing.
- **Rate limits:** Apps Script Web Apps cap at ~20k POSTs/day (free tier). Way more than you'll ever hit personally.
- **Privacy:** the dashboard sends `userAgent` (browser version) and `version` (app version) automatically. No account info, no positions, no API keys.
