// Google Apps Script: receives each submission from the website,
// emails it (with the image attached), saves it to Drive, and logs a row in the Sheet.
// Setup: see README / chat instructions.

var SECRET = 'CHANGE_ME';                         // must equal NOTIFY_SECRET on Render
var EMAILS = 'you@gmail.com,teammate@gmail.com';  // comma-separated recipients
var FOLDER_NAME = 'Grow & Mend designs';

function doPost(e) {
  var d = JSON.parse(e.postData.contents);
  if (d.secret !== SECRET) return ContentService.createTextOutput('forbidden');

  var blob = Utilities.newBlob(Utilities.base64Decode(d.image_b64), 'image/png', d.file);

  var it = DriveApp.getFoldersByName(FOLDER_NAME);
  var folder = it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
  var file = folder.createFile(blob);

  var kind = d.mode === 'fashion' ? 'Upcycled fashion' : 'Green space';
  var who = d.name || 'Anonymous';

  SpreadsheetApp.getActiveSpreadsheet().getActiveSheet()
    .appendRow([new Date(), kind, who, d.note || '', file.getUrl()]);

  MailApp.sendEmail({
    to: EMAILS,
    subject: 'New design: ' + kind + ' from ' + who,
    body: who + ' submitted a ' + kind + ' design.\n\nNote: ' + (d.note || '(none)') + '\n\nDrive: ' + file.getUrl(),
    attachments: [blob]
  });
  return ContentService.createTextOutput('ok');
}
