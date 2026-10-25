BASECOAT FULL TEST BUILD (WINDOWS)

START HERE
1. Extract this ZIP. Do not try to run the app from inside the ZIP preview.
2. Open the extracted Basecoat_Full_Test_Fixed folder.
3. Double-click START_BASECOAT.bat.
4. Leave the black command window open while using Basecoat.
5. In Opera GX (or another browser), open http://127.0.0.1:5000

FIRST RUN
The starter checks for Python 3 and installs the two listed packages (Flask and Werkzeug). This step needs internet access. If no Python is found, the starter prints the install link and stops. Install Python 3.11 or newer from https://www.python.org/downloads/windows/ and select "Add Python to PATH" during setup. Close and reopen the app folder, then double-click START_BASECOAT.bat again.

NEW ACCOUNT AND LOCATION FEATURES
Google sign-in is included, but requires an app owner to create a Google OAuth web client and set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the hosting dashboard; see GO_LIVE_CHECKLIST.md. The local Windows build does not have Google credentials, so Google buttons will explain that setup is needed. A new worker applying with Google stays locked out until the owner approves them under Accounts and selects rank and hourly pay. Customers can create accounts with Google once it is configured.
Workers can optionally consent to share location while clocked in. The owner can set the job boundary from Jobs while at the site and see the worker's latest location in Shift Tracking. Sharing stops at clock-out and pauses when the worker's browser tab is hidden. Browser GPS is approximate and may be stale or unavailable; it cannot stop anyone leaving. Discuss location use clearly with workers and get Michigan legal advice before relying on location data for employment decisions.

TROUBLESHOOTING
- "Python 3 was not found": install Python 3.11+, select Add Python to PATH, then reopen the starter.
- "Address already in use": another app is using port 5000. Close the other Basecoat window/server and try again.
- Browser says site can't be reached: the server is not running. Start it with START_BASECOAT.bat and keep its window open. Look for Flask's message that it is running on http://127.0.0.1:5000. Opera GX is fine; the browser does not need a special setting.
- To check that the server is responding, open http://127.0.0.1:5000/api/health. It should show a small JSON response containing "ok": true.
- Windows Firewall may ask to allow Python. For local use, allow access on private networks only.
- If dependency installation fails, check internet access and run the starter again.

TEST ACCOUNTS
Owner: jroliverioxxxx@gmail.com / 321
Worker: worker@basecoat.local / basecoat123
Customer: customer@basecoat.local / basecoat123

The owner password is for this local demo only. Do not use this build as a public production deployment. The payment screen is a simulation and does not charge a card. Data is stored locally in basecoat.db and uploads/ beside the server files.

FEATURES
Flask backend, SQLite, role login, jobs, job-site and rank group messaging, worker time entries, photo uploads, blueprint PNG save/export and job-card previews, inspection reports, customer job requests, and demo invoice/payment flow.

BLUEPRINTS AND JOB UPDATES
Each job card now has a Blueprint button. Open it to draw or edit that job's plan. The Blueprint Studio includes freehand drawing, walls, room rectangles, lines, doors, windows, dimensions, text notes, an eraser, color/line size, undo/redo, PNG export, and job-specific save/load. Use Ctrl+Z to undo, Ctrl+Y or Ctrl+Shift+Z to redo (Command+Z / Command+Shift+Z on Mac); shortcuts are ignored while typing into a field. The crew can open the saved blueprint from the same job. Use Send to Crew to save it for that job; the build stores it locally with the app.

Job cards also show job status, address, and estimated total. Use Update progress to change completion, Edit details to revise job information, or Delete job to remove the job and its related local photos, messages, invoice, and blueprints. Deletion cannot be undone.

MEASURED SHAPE SIDES
Calibrate the drawing first. Room rectangles and squares show a dimension on each side; circles show diameter; lines and walls show their length; Points Shape labels each edge after you close the outline by clicking its green start point or choosing Close Outline & Finish; doors and windows show their span. Orange dashed dimension guides use separate hollow endpoint circles so they are visually distinct from the drawn shape. Use Points Shape for an irregular shape whose individual sides need measurements. Free Draw shows the overall path length. Use the Dimension tool to add any extra measurement. Saved drawings are flat PNG images, so old shapes from an earlier version need to be redrawn with these tools to gain the new automatic labels.

WORKER PAY
Open Workers, then choose Manage salary and pay for a worker. Change their hourly rate, review the estimate based on completed clock entries, or record a bonus/deduction with a reason. Deductions require the documented-authorization confirmation. This is a local demo record and estimate only: it does not send money, calculate official payroll, or automatically take money from a worker.

WORKERS, RANKS, AND MESSAGES
From the owner account, open Workers to assign a crew rank, manage pay, or fire/reactivate a worker. Firing disables the worker's login and removes their group memberships, while preserving pay and work history. Open Ranks to add, rename, or delete ranks. Use the rank checkboxes to grant chat-member management (foreman responsibility) and inspection reporting. Save rank changes with the Save rank button. Assigning a rank adds the worker to its rank group chat.

The Messages page contains the original owner/assigned-worker/customer job conversation. Team chats contains rank chats and separate job-site chats. Active workers can use groups they belong to. The owner or a worker with a rank that grants chat-member management can add or remove active workers in any group; only the owner can change ranks, fire workers, or manage pay. Job assignment updates job-site chat membership. The demo customer account is customer@basecoat.local / basecoat123.

JOB REQUESTS, INSPECTIONS, AND REQUEST BLOCK LIST
Customers use Request a Job to submit a description, site address, preferred date, and optional budget. A request is not a contract or accepted estimate. The owner or an authorized foreman can review, accept (which creates a job and site chat), or decline it with a note. Inspectors can save a 1–5 quality rating and findings, attach up to 10 issue photos, and click a saved job blueprint to place numbered pins where problems appear. They can choose Top (XY), Side (XZ), or Front (YZ). Each report keeps a snapshot of the blueprint used, so later blueprint edits do not move old issue pins. Owners and authorized inspectors can review reports from job cards or Inspections. Save a blueprint view in Blueprint Studio before placing pins; photos and notes still work without one. The owner-only Request Block List prevents a listed customer from sending new requests in this demo; it does not erase their history or establish legal liability.

TERMS OF SERVICE DRAFT
The Terms of Service page in the app and the included Basecoat_Terms_of_Service_Draft.md are drafts only. Add business and location-specific details and have a construction attorney review before use. The draft supports pausing work and lawful collection or lien remedies where permitted. It does not authorize damaging installed work or waive responsibility for damage Basecoat causes. Job-site laws may require written-contract terms, cancellation notices, payment protections, licensing information, and other disclosures.

After replacing an older extracted folder with this updated build, open the ZIP's folder and run START_BASECOAT.bat again. Existing local data is kept in the folder where that server was run; separate extracted folders have separate local databases and uploads.

EASY DRAWING CONTROLS
For a circle or square, choose its tool and drag across the canvas. For a custom polygon, choose Points Shape and click each corner. The first point is outlined in green; click it to close the outline, or click Close Outline & Finish. If you change tools before finishing, the unfinished point shape is discarded. Use Undo to remove the last completed edit.

Dimension labels use the calibration scale. Confirm critical measurements on site before construction.

REAL SCALE AND FLAT XYZ VIEWS
Open a job blueprint and choose Calibrate. Drag across a line on the drawing that has a known real length; enter the length and selected units. Dimension labels and cursor coordinates then use that scale. Set Origin by clicking where X=0, Y=0, and Z=0 should be. The Top view shows X/Y, Front shows X/Z, and Side shows Y/Z. Each view saves its own drawing, calibration, units, and origin with the job. Calibrate before placing dimension labels. If you later recalibrate or change units, redraw old dimension labels so the drawing does not show mixed measurements.

HOW TO SET REAL SCALE AND XYZ
1. Open the job's Blueprint button and pick Top (X/Y), Front (X/Z), or Side (Y/Z).
2. Pick Feet, Inches, Meters, or Centimeters.
3. Choose Calibrate. Drag over a length whose real measurement you know, then enter that measurement. This sets drawing pixels per unit for the selected view.
4. Choose Set Origin and click the point that should be X 0, Y 0, Z 0.
5. Draw dimensions. Move the pointer over the drawing to read the point's X, Y, and Z coordinates. Save to this job; changing views saves the current view automatically.

The three views are separate flat drawings. Their cursor coordinates use the selected plane axes; they do not combine into a full 3D model. If you recalibrate or change units after adding dimension labels, redraw those labels so the text reflects the new scale. Check critical dimensions on site.


UPDATING AN OLDER COPY
If you already have an older extracted folder, extract this new ZIP to a new folder. To keep that folder's demo data, copy its basecoat.db and uploads folder into the new extracted folder before starting it. Keep the old copy until you confirm the new one has your data.


JOB PRICING CALCULATOR
From Jobs, choose + New Job to open the calculator. Select a work type, enter drywall sheets, crew size, hourly pay and other job costs. Estimated hours per worker start from the selected work type and sheet count; you can edit that time. The assigned worker's saved hourly rate fills in when selected, and the hourly amount remains editable.

Suggested customer price = (drywall sheets × drywall cost per sheet) + (crew size × hours per worker × hourly pay) + other job costs + planned profit. The price cannot be saved with planned profit below $500, and Pricing Settings can raise that minimum. You can enter a higher customer price. Defaults start at $15 per sheet and $22 per worker-hour. Work-type labor factors are starting estimates and can be changed in Pricing Settings. Add all relevant job costs to the other-costs field; the calculator does not determine sales tax, permits, overhead, or actual final profit. This is an estimate based on the values entered, not a guarantee of actual profit.

Customer requests must be priced before acceptance. Existing jobs can be updated with Recalculate price. Previously saved jobs retain their original total until recalculated.

MICHIGAN LOCATION
Basecoat_Terms_of_Service_Draft.md was updated with Michigan-specific review links. It remains a draft; use a Michigan construction attorney to check licensing, written-contract terms, cancellation notices, lien rules, and other project-specific requirements before customer use.

PAYMENT REQUESTS AND COMPANY CHAT
When a job is marked Complete, the owner can open Payments and choose Request final payment. The customer sees the outstanding balance in their Payments page. Local demo mode records a simulated payment only. In hosted production, customers use Stripe Checkout and the invoice becomes Paid only after Stripe's signed webhook confirms payment. Payment requests are not sent by email or SMS in this build.

Team chats includes Everyone · Company Chat for the owner and active workers, in addition to rank chats and job-site chats. Company-chat membership follows active worker status; firing a worker removes their access.

OFFICIAL HOSTED SETUP
The app includes render.yaml, production account/password handling, Stripe Checkout/webhook support, and a persistent-disk configuration. It is prepared for deployment, but is not online until a private code repository, Render account, owner secrets, and Stripe keys are configured. See GO_LIVE_CHECKLIST.md for the steps, current limitations, and estimated provider charges. Never upload local basecoat.db, uploads, or payment secrets to GitHub.
