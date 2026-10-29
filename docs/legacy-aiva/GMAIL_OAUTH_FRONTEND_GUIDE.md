# Gmail OAuth Return-To-App Frontend Guide

## What this document is for

This guide explains the **frontend work** needed so that after a user connects a Gmail account, they are brought back into the Swift app instead of being left in the browser.

This is written for someone who is new to programming, so it explains:

- what needs to change
- which frontend files matter
- why those files matter
- the technical concepts behind the change

This guide is about the **active Swift app** in this repo:

- `Phase 2.xcodeproj`
- `Phase 2/Phase_2App.swift`
- `Phase-2-Info.plist`
- `Phase 2/Views/AddAppsOverlay.swift`

Do **not** start in the older `v2/tyler/...` app copies unless you are sure that Xcode is running that older project. The active Xcode project in this repo points at `Phase-2-Info.plist`.

---

## The problem in simple terms

Right now the flow works like this:

1. The app asks the backend for a Google OAuth URL.
2. The app opens that URL in the browser.
3. The user signs into Google and grants permission.
4. Google sends the browser to the backend callback URL.
5. The backend stores the Gmail credential.
6. The browser stays in the browser instead of reopening the app.

The missing piece is: **the app has not been set up to receive a final “come back to me” link from the backend**.

---

## The target behavior

After the backend finishes the Google callback, it should redirect the browser to one of these app URLs (can be named anything):

- `aiva://oauth/gmail/success`
- `aiva://oauth/gmail/failure`

When iOS sees `aiva://...`, it should:

1. recognize that `aiva` belongs to this app
2. reopen the app
3. let the app react to the result

Then the app should:

- on success: refetch credentials from the backend and mark Gmail as connected
- on failure: show an error message

---

## The main concepts

Before touching code, these are the concepts to understand.

### 1. OAuth

OAuth is the flow where a user gives one app permission to access another service. In this case:

- the user is in Aiva
- Aiva wants access to Gmail
- Google shows the permission screen
- Google sends the result back to the backend

Important detail: the **backend** is still the system that exchanges the Google code for tokens. The app does **not** need to handle Google tokens directly in this flow.

### 2. Redirect URI

A redirect URI is the URL that Google sends the browser to after the user finishes the consent screen.

For this project, that redirect URI should remain the backend callback, for example:

`http://127.0.0.1:8000/plugins/oauth/callback/gmail/`

That is the Google-facing callback. It is not the same thing as reopening the app.

### 3. Deep link

A deep link is a URL that opens the app and optionally tells it what screen or action to handle.

In this guide, the deep link is:

- `aiva://oauth/gmail/success`
- `aiva://oauth/gmail/failure`

This is how the backend tells iOS: “Google is done, send the user back into Aiva.”

### 4. URL scheme

The URL scheme is the first part of a URL:

- `https://example.com`
- `mailto:test@example.com`
- `aiva://oauth/gmail/success`

Here, the scheme is `aiva`.

If the app registers the `aiva` scheme in its app configuration, iOS knows that links starting with `aiva://` belong to this app.

### 5. `Info.plist`

`Info.plist` is an app configuration file. It tells iOS important facts about the app, such as:

- permissions
- bundle information
- supported URL schemes

For this repo, the active app uses:

- `Phase-2-Info.plist`

### 6. `.onOpenURL`

In SwiftUI, `.onOpenURL` is how the app reacts when iOS opens it using a URL.

That is the piece that lets the app say:

- “I just received `aiva://oauth/gmail/success`”
- “Now I should refresh Gmail credentials and update the UI”

### 7. NotificationCenter

`NotificationCenter` is a lightweight message system inside the app.

One part of the app can send a message:

- “Gmail OAuth succeeded”

Another part of the app can listen for it:

- “If that happens while the Add Apps overlay is open, refresh the UI”

This is useful here because:

- `Phase_2App.swift` is the top-level app entrypoint
- `AddAppsOverlay.swift` is a specific screen
- they are not the same layer of the app

---

## Files to look at

These are the important frontend files for this task.

### 1. `Phase 2.xcodeproj/project.pbxproj`

Why look at it:

- It confirms which `Info.plist` file the active app target uses.

What matters here:

- the active app target points at `Phase-2-Info.plist`

Why this matters:

- without this check, it is easy to accidentally edit an older plist in `v2/tyler/...` and then wonder why nothing changes in the running app

Usually this file does **not** need to be changed for this task.

### 2. `Phase-2-Info.plist`

Why look at it:

- this is where the app must declare that it supports the `aiva` URL scheme

Why it matters:

- without this, iOS will not know that `aiva://...` should open this app

### 3. `Phase 2/Phase_2App.swift`

Why look at it:

- this is the top-level SwiftUI app entrypoint
- it is the best place to catch deep links using `.onOpenURL`

Why it matters:

- if the app does not listen for the URL, it will open but do nothing useful

### 4. `Phase 2/Views/AddAppsOverlay.swift`

Why look at it:

- this file already contains the Gmail connection flow
- it already requests the backend OAuth URL
- it already opens the browser
- it already polls `/plugins/credentials/`

Why it matters:

- this is where the UI should react when Gmail OAuth succeeds or fails

---

## What to change

## Step 1: Register the app URL scheme in `Phase-2-Info.plist`

### Goal

Tell iOS that URLs beginning with `aiva://` belong to this app.

### Why this is required

Without this, the backend can redirect to `aiva://oauth/gmail/success`, but iOS will not know what app should handle it.

### What to add

Add a `CFBundleURLTypes` section to `Phase-2-Info.plist` if it is missing.

Example:

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLName</key>
        <string>Aiva Deep Links</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>aiva</string>
        </array>
    </dict>
</array>
```

### Why `aiva`

`aiva://` is already a good choice in this codebase because the app already uses URLs like:

- `aiva://settings/subscription`

That means the app is already conceptually using `aiva://` as its internal navigation scheme.

### Beginner note

The app does not “get” this scheme from Google. You are defining it yourself. This is app-owned configuration.

---

## Step 2: Handle incoming deep links in `Phase 2/Phase_2App.swift`

### Goal

Make the app react when iOS opens it using:

- `aiva://oauth/gmail/success`
- `aiva://oauth/gmail/failure`

### Why this file is the right place

`Phase_2App.swift` is the app entrypoint. That means:

- it exists for the whole life of the app
- it can catch links no matter which screen is currently on screen

### What to add conceptually

Add `.onOpenURL` to the root SwiftUI view.

Inside it:

1. check that the scheme is `aiva`
2. check that the host/path match the Gmail OAuth result routes
3. post an internal notification that other screens can listen to

### Important technical detail: URL parsing

For this URL:

`aiva://oauth/gmail/success`

Swift usually reads it as:

- `scheme = "aiva"`
- `host = "oauth"`
- `path = "/gmail/success"`

That means the app should check:

- scheme equals `aiva`
- host equals `oauth`
- path equals `/gmail/success` or `/gmail/failure`

This is a very common beginner mistake: expecting the path to be `/oauth/gmail/success`. It usually is not.

### Suggested internal event names

Use notification names like:

- `AivaGmailOAuthSucceeded`
- `AivaGmailOAuthFailed`

### Why notifications are useful here

The app entrypoint should not directly reach into a specific overlay and mutate its state. That creates tight coupling.

A cleaner flow is:

1. app entrypoint receives the URL
2. app entrypoint broadcasts an internal event
3. `AddAppsOverlay.swift` listens for it and updates itself

---

## Step 3: Update `Phase 2/Views/AddAppsOverlay.swift` to react to success/failure

### What this file already does

This file already:

- loads the Supabase JWT from storage
- calls `POST /plugins/oauth/connect/`
- gets back `auth_url`
- opens the browser
- polls `GET /plugins/credentials/` for up to 75 seconds

### Why it still needs changes

Right now the overlay only knows how to wait and poll. It does not know when the app has been reopened by a deep link.

That means:

- the user may return to the app but the overlay still behaves as if nothing special happened
- the UI update is slower than it needs to be
- failure handling is weaker than it should be

### What to change

Add logic so the overlay listens for the internal Gmail OAuth notifications.

#### On success

When the overlay hears the success event, it should:

1. stop or short-circuit the waiting state
2. call `fetchCredentials(token:)`
3. find the Gmail credential
4. store the account ID/email using the existing persistence logic
5. mark Gmail as selected
6. close the connect form

#### On failure

When the overlay hears the failure event, it should:

1. stop the loading state
2. set a friendly error message
3. show the existing error UI

### Recommended cleanup

This file currently has duplicated “success UI update” logic inside the poll loop.

A better structure is to extract that into one helper function, such as:

- `completeGmailConnection(accountId:)`

That helper would contain the shared UI logic:

- persist connected account
- mark Gmail selected
- close the form

Then both of these paths can call the same helper:

- polling success
- deep-link success

This reduces bugs because the UI update is defined in one place instead of copied in multiple places.

### Keep or remove polling?

For this project, the safest short-term choice is:

- **keep polling as a fallback**
- but add deep-link handling for the main path

Why:

- if deep linking is temporarily broken, the old poll logic still gives the user a chance to finish the flow
- this reduces risk while the feature is being wired up

Later, if deep linking proves reliable, polling can be reduced or removed.

---

## Step 4: Keep the frontend/backend contract clear

This document is frontend-focused, but the frontend developer needs to know the contract it is depending on.

The frontend should assume the backend will do this:

### Success

After the backend receives Google’s callback and saves the credential, it redirects to:

`aiva://oauth/gmail/success`

### Failure

If something goes wrong, it redirects to:

`aiva://oauth/gmail/failure`

### Important boundary

The frontend is **not** receiving raw Google tokens directly from the browser redirect.

Instead:

1. backend handles Google callback
2. backend stores credential
3. backend sends browser back to app
4. app asks backend for current credentials

This is a cleaner separation because the app is not responsible for the sensitive token exchange step.

---

## A simple implementation order

If someone new is doing this work, this is the safest order.

### 1. Make the app open from `aiva://...`

Work in:

- `Phase-2-Info.plist`

Test by typing a URL like `aiva://oauth/gmail/success` in Safari on the simulator.

If the app does not open, do not move on yet.

### 2. Make the app log incoming URLs

Work in:

- `Phase 2/Phase_2App.swift`

Add `.onOpenURL` and temporarily print the received URL.

Test again with Safari in the simulator.

If the app opens but nothing prints, fix that before moving on.

### 3. Convert the incoming URL into app events

Still in:

- `Phase 2/Phase_2App.swift`

When a success or failure URL arrives, post a notification.

### 4. Make the overlay respond to those events

Work in:

- `Phase 2/Views/AddAppsOverlay.swift`

Listen for success/failure notifications and update the UI.

### 5. Run the full Gmail connect flow

Start from the overlay and test the full browser round-trip.

---

## What the final user experience should feel like

When this is finished, the user should experience the Gmail connection flow like this:

1. Tap Gmail connect in the app.
2. Browser opens the Google consent page.
3. User approves Gmail access.
4. Browser briefly visits the backend callback.
5. App opens again automatically.
6. Gmail is shown as connected in the overlay.

If something fails:

1. App opens again automatically.
2. User sees a clear error message instead of getting stranded in the browser.

---

## Common mistakes to avoid

### Mistake 1: Editing the wrong plist

Do not edit one of the older `v2/tyler/...` plist files unless you are actually building that older project.

For the active app, use:

- `Phase-2-Info.plist`

### Mistake 2: Trying to make Google redirect directly to `aiva://...`

That is not the plan here.

Google should still redirect to the backend callback URL. The backend then redirects to the app.

### Mistake 3: Forgetting that `oauth` is the host

For `aiva://oauth/gmail/success`:

- host is `oauth`
- path is `/gmail/success`

If the code checks the wrong path shape, the deep link handler will silently fail.

### Mistake 4: Only opening the app, but not updating the UI

Reopening the app is only half the job. The screen still needs to:

- fetch credentials
- persist account data
- update visible state

### Mistake 5: Removing polling too early

Keep the current poll logic at first. It is a good safety net while deep links are being introduced.

---

## Manual test checklist

Use this checklist when testing in Xcode Simulator.

### Deep link test

1. Build and run the app in the simulator.
2. Open Safari in the simulator.
3. Enter `aiva://oauth/gmail/success`.
4. Confirm the app opens.

If that fails, the URL scheme is not wired correctly yet.

### App handler test

1. Trigger the same deep link again.
2. Confirm `.onOpenURL` runs.
3. Confirm the app posts the success notification.

### Overlay reaction test

1. Open the Add Apps overlay.
2. Trigger `aiva://oauth/gmail/success`.
3. Confirm the overlay reacts without needing a manual reopen.

### Full Gmail flow test

1. Start Gmail connect from the overlay.
2. Finish Google consent in the browser.
3. Confirm the app returns automatically.
4. Confirm Gmail shows as connected.

### Failure test

1. Trigger `aiva://oauth/gmail/failure`.
2. Confirm the app opens.
3. Confirm the overlay shows a failure message.

---

## Recommended frontend scope for this task

To keep the change small and safe, the frontend work should stay limited to:

- `Phase-2-Info.plist`
- `Phase 2/Phase_2App.swift`
- `Phase 2/Views/AddAppsOverlay.swift`

That is enough to:

- receive the return link
- reopen the app
- update the Gmail connection UI

It is not necessary to redesign the whole auth system or replace the existing overlay architecture for this task.

---

## Short version

If you only remember one sentence, remember this:

**The app needs to register `aiva://` in `Phase-2-Info.plist`, catch that URL in `Phase_2App.swift`, and let `AddAppsOverlay.swift` react when Gmail OAuth succeeds or fails.**
