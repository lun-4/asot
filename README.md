# asot

**asot is PoC level software. just use https://github.com/ekzhang/bore**

"a series of tubes".

tcp tunneling to localhost in a BYOOP model, bring your own on-premises.

attempting to make a functional thing in 690 lines of code. then expanding to
1kloc or 1.5kloc if i can support windows

## the alternatives i know of

ngrok

- works
- has limits for free users, which makes sense, money is important

pagekite

- works, until you need to restart your webapp, now it broke and needs a restart

localhost.run

- works
- only http i think
- not a lot of feedback to understand if it broke or not

the only possible solution ever is to make my own using my infra just
because it would be funny to do so
