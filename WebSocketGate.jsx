// Standalone JSX for the XRay WebSocket fallback page.
// It is loaded from the raw GitHub URL by the generated proxy page.
const { useEffect, useRef } = React;

function App() {
  const animationRef = useRef(null);

  useEffect(() => {
    let animation;
    let cancelled = false;

    const start = async () => {
      try {
        if (!window.lottie) {
          await new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = "https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js";
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
          });
        }
        const response = await fetch(
          "https://raw.githubusercontent.com/i-execute/Media/main/Animation/Evil_Rat.json"
        );
        if (!response.ok) throw new Error(`animation_${response.status}`);
        const animationData = await response.json();
        if (!cancelled && animationRef.current) {
          animation = window.lottie.loadAnimation({
            container: animationRef.current,
            renderer: "svg",
            loop: true,
            autoplay: true,
            animationData,
          });
        }
      } catch (error) {
        if (!cancelled && animationRef.current) animationRef.current.textContent = "◌";
        console.warn("WebSocketGate animation unavailable", error);
      }
    };

    start();
    return () => {
      cancelled = true;
      if (animation) animation.destroy();
    };
  }, []);

  return React.createElement(
    "main",
    { className: "gate" },
    React.createElement("div", { className: "orb", ref: animationRef }),
    React.createElement("div", { className: "title" }, "secure channel"),
    React.createElement("div", { className: "subtitle" }, "initializing…")
  );
}

window.App = App;
