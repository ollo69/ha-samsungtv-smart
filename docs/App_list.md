# HomeAssistant - SamsungTV Smart Component

***app_list guide***
---------------

**Note:** Although this is an optional value, **it is highly recommended to set it manually**, even if in some (rare) cases the app list can be gotten from the TV successfully.

The `app_list` is used to set apps that you have installed on your TV. The app names can be associated with 2 types of IDs that Samsung TVs support: numerical IDs and alphanumerical IDs.

An application normally has both a numerical ID and an alphanumerical ID associated with it.

Here are some known lists of app IDs: [List 1](https://github.com/tavicu/homebridge-samsung-tizen/issues/26#issuecomment-447424879), [List 2](https://github.com/Ape/samsungctl/issues/75#issuecomment-404941201)

(Another way of finding the alphanumerical ID is by enabling the [SmartThings API](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md) and running an app on the TV, this will show the alphanumerical ID as `media_title` in the component)

Here are 3 examples values for `app_list`:
- `'{"Netflix": "3201907018807", "Prime Video": "3201910019365", "Spotify": "3201606009684"}'`
- `'{"Netflix": "org.tizen.netflix-app", "Prime Video": "org.tizen.primevideo", "Spotify": "3201606009684"}'`
- `'{"Netflix": "3201907018807/org.tizen.netflix-app", "Prime Video": "3201910019365/org.tizen.primevideo", "Spotify": "3201606009684"}'`

(the last one is the prefered method, which includes both numerical and alphanumerical IDs, for increased support of this component)

In order to understand these example values, you must first understand what these IDs are used for.

An app ID is used to start the app on the TV and also to identify the running app on the TV.

To run the app on the TV, both numerical and alphanumerical IDs can be used.

To get the running app from the TV, two different ways are used:
- one works only with numerical IDs by doing HTTP polling on the TV (1 request for each app in `app_list`), this is a lengthy task that should be avoided if possible (this can be completely avoided by setting `scan_app_http` to `False` in your component's config)
- another works only with the alphanumerical IDs by getting the running app from the SmartThings API (requires SmartThings API enabled in your component's config)

**Note:** There is one rare case, for a few apps (like "Prime Video") where the numerical ID will work to start the app, but not to identify the running app, while it's alphanumerical ID will work to get the running app but not run the app. It is for this case that we also allow setting both numerical and alphanumerical IDs at the same time (separated by "/") which will allow this component to correctly handle this rare case too.

