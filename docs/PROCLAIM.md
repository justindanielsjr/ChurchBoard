# Faithlife Proclaim

ChurchBoard controls Proclaim through Faithlife's supported local App Command API. It can move slides and service items, take Proclaim on or off air, follow the exact on-air item and slide, keep ChurchBoard's Planning Center order and timing aligned, and show slide text or a rendered Proclaim NDI output.

## Connect Proclaim

1. On the Proclaim computer, open **Settings → Remote** and enable the local server.
2. In ChurchBoard, open **Setup → Faithlife Proclaim**.
3. Enter the Proclaim computer's address. Keep port **52195**.
4. If ChurchBoard is on another computer, enter the same Remote password configured in Proclaim.
5. Select **Save & test Proclaim**.

Keep ChurchBoard and Proclaim on the same trusted production network. Proclaim allows unauthenticated local-computer requests; network requests should use a password.

## Planning Center service flow

Import the service plan into Proclaim using Proclaim's Planning Center integration, and select the same plan and service time in ChurchBoard. In the Planning Center module's Services LIVE settings, choose **Proclaim** as the presentation source and enable Services LIVE control when desired.

ChurchBoard follows Proclaim's exact service-item index rather than relying only on names. This keeps repeated items—such as pre-service slides used before and after a service—matched to the correct Planning Center row. The Order of Service and timing widgets update when an operator changes items directly in Proclaim or through ChurchBoard.

## Proclaim widgets

- **Proclaim slides** shows current and next slide text. With an NDI source selected, it can instead show the rendered program output.
- **Proclaim playlist** shows the complete on-air service, automatically scrolls to the active slide, and lets an authorized operator select an item or slide directly.
- **Proclaim controls** provides previous/next slide, previous/next item, and on-air/off-air controls.
- **Proclaim timers** shows the active item's configured target duration and counts down while that item is active.

For playlist and slide-text data, ChurchBoard reads Proclaim's local presentation information on the Proclaim computer. If ChurchBoard runs on a different computer, controls and NDI remain available, but locally stored presentation text may not be accessible.

## Accurate rendered slide output

For the actual rendered output—including backgrounds, videos, and visual slide formatting—enable an NDI output in Proclaim:

1. Configure the desired Proclaim screen as an NDI output.
2. Install and enable ChurchBoard's NDI module.
3. Enter the exact source name in **Setup → Faithlife Proclaim → Proclaim NDI source name**.
4. Add a **Proclaim slides** widget to a board.

When an NDI source is configured, the widget shows the rendered Proclaim output. Text mode shows the current slide and the next slide within the same service item whenever one is available.

## Available controls

- Previous slide / Next slide
- Previous item / Next item
- Go on air / Go off air

Add the Proclaim Controls or trigger-enabled Proclaim Playlist widget only to boards intended for operators.
