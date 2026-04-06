"""CLI for audio routing and transcription"""
from __future__ import annotations
import logging
from pathlib import Path
import click

from ..audio_routing.pipeline import AudioRoutingPipeline, load_config

logger = logging.getLogger(__name__)


@click.command(name="audio_route_transcribe")
@click.option(
    '--input', '-i',
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help='Input video file (mp4/mkv/avi/flv)'
)
@click.option(
    '--workdir', '-w',
    type=click.Path(path_type=Path),
    required=True,
    help='Working directory for outputs'
)
@click.option(
    '--refs', '-r',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Reference audio directory (optional)'
)
@click.option(
    '--config', '-c',
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help='Config file (optional, uses defaults if not provided)'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='Enable verbose logging'
)
def audio_route_transcribe_cli(
    input: Path,
    workdir: Path,
    refs: Path,
    config: Path,
    verbose: bool
):
    """
    音频分流和转录工具

    对输入视频进行音频分流，区分主播/TTS/游戏对白/背景音，
    并生成带角色标签的转录文本。

    输出文件：
      - labeled_segments.json: 带角色标签的转录段（关键输出）
      - game_non_speech.json: 游戏背景音/音效段
      - speaker_profiles.json: 说话人角色映射
      - logs.txt: 处理日志

    示例:
      acfv audio_route_transcribe -i input.mp4 -w runs/001/work -r refs/
    """
    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    logger.info("=== Audio Routing & Transcription CLI ===")
    logger.info(f"Input: {input}")
    logger.info(f"Workdir: {workdir}")
    logger.info(f"Refs: {refs}")
    logger.info(f"Config: {config}")
    
    # 加载配置
    if config:
        cfg = load_config(config)
        logger.info("Loaded config from file")
    else:
        cfg = load_config(Path("config/audio_routing.yaml"))  # 尝试默认位置
        logger.info("Using default config")
    
    # 检查refs
    if refs:
        ref_files = list(refs.glob("*.wav")) + list(refs.glob("*.mp3"))
        logger.info(f"Found {len(ref_files)} reference files")
        for ref in ref_files:
            logger.info(f"  - {ref.name}")
    else:
        logger.warning("No reference directory provided, role mapping may be less accurate")
    
    # 运行管道
    pipeline = AudioRoutingPipeline(cfg, workdir)
    success = pipeline.run(input, refs)
    
    if success:
        logger.info("✓ Pipeline completed successfully")
        logger.info(f"Output files saved to: {workdir}")
        logger.info("Key output: labeled_segments.json")
        click.echo(click.style("\n✓ Success!", fg='green', bold=True))
        click.echo(f"Results saved to: {workdir}")
    else:
        logger.error("✗ Pipeline failed")
        click.echo(click.style("\n✗ Failed!", fg='red', bold=True))
        click.echo(f"Check logs: {workdir / 'logs.txt'}")
        raise click.ClickException("Audio routing pipeline failed")


if __name__ == '__main__':
    audio_route_transcribe_cli()
