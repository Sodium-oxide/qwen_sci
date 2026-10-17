import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import qwenLogo from "../assets/qwen-logo.svg?raw";

const fullTurn = Math.PI * 2;

function noise(seed: number) {
  const value = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return value - Math.floor(value);
}

function createGlow(color: string) {
  const sprite = document.createElement("canvas");
  sprite.width = 32;
  sprite.height = 32;
  const context = sprite.getContext("2d");
  if (context) {
    const glow = context.createRadialGradient(16, 16, 0, 16, 16, 16);
    glow.addColorStop(0, "#ffffff");
    glow.addColorStop(0.12, color);
    glow.addColorStop(0.35, `${color}70`);
    glow.addColorStop(1, `${color}00`);
    context.fillStyle = glow;
    context.fillRect(0, 0, 32, 32);
  }
  return sprite;
}

function createLogoField(compact: boolean) {
  const fieldSize = 256;
  const source = new DOMParser().parseFromString(qwenLogo, "image/svg+xml");
  const [viewX, viewY, viewWidth, viewHeight] = source.documentElement.getAttribute("viewBox")!.split(/\s+/).map(Number);
  const directions = [
    { horizontal: 1, vertical: 0 },
    { horizontal: -0.5, vertical: -Math.sqrt(3) / 2 },
    { horizontal: -0.5, vertical: Math.sqrt(3) / 2 },
  ];
  const spacing = compact ? 5 : 4;
  const sprites = [createGlow("#557fff"), createGlow("#8aafff"), createGlow("#c9ddff")];
  return Array.from(source.querySelectorAll("path"), (path, arm) => {
    const mask = document.createElement("canvas");
    mask.width = fieldSize;
    mask.height = fieldSize;
    const context = mask.getContext("2d", { willReadFrequently: true })!;
    context.scale(fieldSize / viewWidth, fieldSize / viewHeight);
    context.translate(-viewX, -viewY);
    context.fill(new Path2D(path.getAttribute("d")!));
    const alpha = context.getImageData(0, 0, fieldSize, fieldSize).data;
    const particles = [];
    for (let vertical = 0; vertical < fieldSize; vertical += spacing) {
      for (let horizontal = 0; horizontal < fieldSize; horizontal += spacing) {
        const seed: number = particles.length + arm * 5000;
        particles.push({
          horizontal: horizontal + noise(seed + 90) * spacing,
          vertical: vertical + noise(seed + 130) * spacing,
          speed: 6 + noise(seed + 170) * 5,
          phase: noise(seed + 210) * fullTurn,
          size: 0.5 + noise(seed + 250) ** 2 * 0.65,
          opacity: 0.45 + noise(seed + 290) * 0.55,
          sprite: sprites[seed % sprites.length],
        });
      }
    }
    return { alpha, direction: directions[arm], particles };
  });
}

function createScene(width: number, height: number) {
  const centerX = width * 0.51;
  const centerY = height * 0.465;
  const radius = Math.min(width * 0.325, height * 0.35);
  const tilt = 0.17;
  const cosine = Math.cos(tilt);
  const sine = Math.sin(tilt);
  const ringPoint = (angle: number, lane: number) => {
    const ringRadius = width * (0.425 + lane * 0.0028);
    const localX = Math.cos(angle) * ringRadius;
    const localY = Math.sin(angle) * ringRadius * 0.27;
    return {
      horizontal: centerX + localX * cosine - localY * sine,
      vertical: centerY + height * 0.045 + localX * sine + localY * cosine,
    };
  };
  const buildLayer = (paint: (context: CanvasRenderingContext2D) => void) => {
    const layer = document.createElement("canvas");
    layer.width = Math.round(width * 2);
    layer.height = Math.round(height * 2);
    const context = layer.getContext("2d");
    if (context) {
      context.scale(2, 2);
      paint(context);
    }
    return layer;
  };
  const paintTracks = (context: CanvasRenderingContext2D, front: boolean) => {
    for (let lane = -12; lane < 23; lane += 1) {
      context.beginPath();
      for (let step = 0; step <= 100; step += 1) {
        const angle = (front ? 0 : Math.PI) + step * Math.PI / 100;
        const point = ringPoint(angle, lane);
        if (step === 0) context.moveTo(point.horizontal, point.vertical);
        else context.lineTo(point.horizontal, point.vertical);
      }
      context.strokeStyle = `rgba(144, 166, 255, ${front ? 0.035 + noise(lane) * 0.085 : 0.025})`;
      context.lineWidth = lane % 9 === 0 ? 1.1 : 0.45;
      context.stroke();
    }
  };
  const backdrop = buildLayer((context) => {
    for (let index = 0; index < 150; index += 1) {
      context.fillStyle = `rgba(150, 170, 255, ${0.08 + noise(index + 400) * 0.28})`;
      context.beginPath();
      context.arc(noise(index) * width, noise(index + 200) * height, noise(index + 600) * 0.9 + 0.25, 0, fullTurn);
      context.fill();
    }
    paintTracks(context, false);
  });
  const core = buildLayer((context) => {
    const atmosphere = context.createRadialGradient(centerX, centerY, radius * 0.7, centerX, centerY, radius * 1.3);
    atmosphere.addColorStop(0, "#3d60ff00");
    atmosphere.addColorStop(0.65, "#3d60ff16");
    atmosphere.addColorStop(1, "#3d60ff00");
    context.fillStyle = atmosphere;
    context.fillRect(0, 0, width, height);
    const surface = context.createRadialGradient(centerX - radius * 0.4, centerY - radius * 0.55, 0, centerX, centerY, radius);
    surface.addColorStop(0, "#262d54");
    surface.addColorStop(0.65, "#171d38");
    surface.addColorStop(0.94, "#101426");
    surface.addColorStop(1, "#424f83");
    context.beginPath();
    context.arc(centerX, centerY, radius, 0, fullTurn);
    context.fillStyle = surface;
    context.fill();
    const rim = context.createLinearGradient(centerX - radius, centerY - radius, centerX + radius, centerY + radius);
    rim.addColorStop(0, "#e2e8ff");
    rim.addColorStop(0.3, "#9eafffb0");
    rim.addColorStop(0.65, "#4f64a530");
    rim.addColorStop(1, "#91a5ff55");
    context.strokeStyle = rim;
    context.lineWidth = 2.2;
    context.stroke();
    context.beginPath();
    context.arc(centerX, centerY, radius + 3.5, 0, fullTurn);
    context.strokeStyle = "#94a8ff22";
    context.lineWidth = 3;
    context.stroke();
  });
  const foreground = buildLayer((context) => paintTracks(context, true));
  const sprites = [createGlow("#829bff"), createGlow("#b6c6ff"), createGlow("#e3eaff")];
  const particles = Array.from({ length: width < 450 ? 480 : 920 }, (_, index) => ({
    phase: noise(index + 10) * fullTurn,
    lane: noise(index + 20) * 42 - 15,
    speed: 0.055 + noise(index + 30) * 0.045,
    size: 0.45 + noise(index + 40) ** 4 * 1.8,
    opacity: 0.25 + noise(index + 50) * 0.75,
    sprite: sprites[index % sprites.length],
  }));
  const logoField = createLogoField(width < 450);
  const logoWidth = width * 0.35;
  const logoHeight = logoWidth * 52 / 51;
  const logoLeft = centerX - logoWidth / 2;
  const logoTop = height * 0.37 - logoHeight / 2;

  const paintLogo = (context: CanvasRenderingContext2D, elapsed: number) => {
    context.globalCompositeOperation = "lighter";
    for (const stream of logoField) {
      for (const particle of stream.particles) {
        const travel = elapsed * particle.speed;
        const horizontal = ((particle.horizontal + travel * stream.direction.horizontal) % 256 + 256) % 256;
        const vertical = ((particle.vertical + travel * stream.direction.vertical) % 256 + 256) % 256;
        const coverage = stream.alpha[(Math.floor(vertical) * 256 + Math.floor(horizontal)) * 4 + 3] / 255;
        if (coverage === 0) continue;
        const highlight = 0.66 + Math.sin(horizontal * 0.04 + vertical * 0.035 - elapsed * 0.9 + particle.phase * 0.25) * 0.24;
        const size = particle.size * (width < 450 ? 5.5 : 7);
        context.globalAlpha = coverage * particle.opacity * highlight;
        const positionX = logoLeft + horizontal / 256 * logoWidth;
        const positionY = logoTop + vertical / 256 * logoHeight;
        context.drawImage(particle.sprite, positionX - size / 2, positionY - size / 2, size, size);
      }
    }
    context.globalAlpha = 1;
    context.globalCompositeOperation = "source-over";
  };

  return (context: CanvasRenderingContext2D, elapsed: number) => {
    context.clearRect(0, 0, width, height);
    context.drawImage(backdrop, 0, 0, width, height);
    const paintParticles = (front: boolean) => {
      context.globalCompositeOperation = "lighter";
      for (const particle of particles) {
        const angle = (particle.phase + elapsed * particle.speed) % fullTurn;
        if ((Math.sin(angle) >= 0) !== front) continue;
        const point = ringPoint(angle, particle.lane);
        const depth = front ? 0.65 + Math.sin(angle) * 0.35 : 0.24;
        const size = particle.size * (front ? 8 : 5);
        context.globalAlpha = particle.opacity * depth;
        context.drawImage(particle.sprite, point.horizontal - size / 2, point.vertical - size / 2, size, size);
      }
      context.globalAlpha = 1;
      context.globalCompositeOperation = "source-over";
    };
    paintParticles(false);
    context.drawImage(core, 0, 0, width, height);
    paintLogo(context, elapsed);
    context.drawImage(foreground, 0, 0, width, height);
    paintParticles(true);
  };
}

export function QwenParticleVisual() {
  const containerRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const elapsedRef = useRef(0);
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(preference.matches);
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!container || !canvas || !context) return;
    let frame = 0;
    let lastTime = 0;
    let visible = true;
    let paint: ReturnType<typeof createScene> | undefined;

    const animate = (timestamp: number) => {
      if (lastTime === 0 || timestamp - lastTime >= 1000 / 30) {
        if (lastTime) elapsedRef.current += Math.min((timestamp - lastTime) / 1000, 0.1);
        lastTime = timestamp;
        paint?.(context, elapsedRef.current);
      }
      frame = requestAnimationFrame(animate);
    };
    const synchronize = () => {
      cancelAnimationFrame(frame);
      lastTime = 0;
      paint?.(context, elapsedRef.current);
      if (visible && !document.hidden && !paused && !reducedMotion) frame = requestAnimationFrame(animate);
    };
    const resize = () => {
      const { width, height } = container.getBoundingClientRect();
      if (width === 0 || height === 0) return;
      const resolution = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * resolution);
      canvas.height = Math.round(height * resolution);
      context.setTransform(resolution, 0, 0, resolution, 0, 0);
      paint = createScene(width, height);
      synchronize();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      synchronize();
    });
    intersection.observe(container);
    document.addEventListener("visibilitychange", synchronize);
    resize();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      intersection.disconnect();
      document.removeEventListener("visibilitychange", synchronize);
    };
  }, [paused, reducedMotion]);

  return (
    <figure className="hero-visual qwen-particle-visual" ref={containerRef} aria-label="由蓝白色流动粒子组成的 Qwen Logo 与环绕光环">
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="qwen-particle-brand">
        <span>QwenSci</span>
      </div>
      <figcaption>问题 · 证据 · 研究</figcaption>
      {!reducedMotion && (
        <button className="particle-motion-control" type="button" aria-pressed={paused} onClick={() => setPaused(!paused)}>
          {paused ? <Play size={13} aria-hidden="true" /> : <Pause size={13} aria-hidden="true" />}
          {paused ? "播放动效" : "暂停动效"}
        </button>
      )}
    </figure>
  );
}
