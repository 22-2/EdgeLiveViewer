#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import random
import logging
import time
import re  # ここを追加
from PyQt5.QtWidgets import (QWidget, QApplication)
from PyQt5.QtCore import (Qt, QTimer, QRect, QPoint, QSize, QThread, pyqtSignal, QBuffer, QByteArray, QEvent)
from PyQt5.QtGui import (QFont, QColor, QPainter, QFontMetrics, QPen, QBrush, QImage, QMovie, QPixmap, QCursor)
import requests
from io import BytesIO
import threading
from queue import Queue, Empty

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('CommentOverlayWindow')

class CommentObject:
    """コメントデータを保持するための軽量クラス"""
    __slots__ = [
        'id', 'text', 'x', 'y', 'width', 'height', 'row', 
        'creation_time', 'speed', 'number', 'is_system', 'pixmap'
    ]

    def __init__(self, **kwargs):
        # is_systemのデフォルト値を設定
        self.is_system = False
        # kwargsで渡された属性をセット
        for key, value in kwargs.items():
            setattr(self, key, value)

class ImageLoaderThread(QThread):
    """画像読み込み用のスレッド"""
    # ★★★ 変更点1: シグナルの定義を変更 ★★★
    # QImageではなく、ダウンロードした生のデータ(bytes)とコンテンツタイプ(str)を渡す
    image_loaded = pyqtSignal(str, bytes, str, str)  # url, content_bytes, comment_id, content_type

    def __init__(self, url_queue):
        super().__init__()
        self.url_queue = url_queue
        self.running = True
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def run(self):
        while self.running:
            try:
                # キューからURLとコメントIDを取得
                url_data = self.url_queue.get(timeout=1)
                url, comment_id = url_data if isinstance(url_data, tuple) else (url_data, None)
                try:
                    logger.info(f"画像の読み込みを開始: {url}, comment_id={comment_id}")
                    
                    max_retries = 3
                    retry_delay = 2
                    
                    for attempt in range(max_retries):
                        try:
                            # ★★★ 変更点2: ここで全てのダウンロードを完結させる ★★★
                            response = requests.get(url, headers=self.headers, timeout=5)
                            if response.status_code == 200:
                                # 生のバイトデータを取得
                                content_bytes = response.content
                                # Content-Typeヘッダーを取得
                                content_type = response.headers.get('Content-Type', '')
                                
                                logger.info(f"画像のダウンロード成功: {url}, type: {content_type}")
                                # シグナルで生のデータとコンテンツタイプをメインスレッドに送信
                                self.image_loaded.emit(url, content_bytes, comment_id, content_type)
                                break
                            # ... (以降のリトライ処理は変更なし) ...
                            elif response.status_code == 429:
                                if attempt < max_retries - 1:
                                    wait_time = retry_delay * (2 ** attempt)
                                    logger.warning(f"レート制限に引っかかりました。{wait_time}秒後にリトライします。(試行回数: {attempt + 1}/{max_retries})")
                                    time.sleep(wait_time)
                                    continue
                                else:
                                    logger.error(f"最大リトライ回数に達しました: {url}")
                            else:
                                logger.error(f"画像のダウンロードに失敗: HTTP {response.status_code}")
                                break
                        except requests.exceptions.RequestException as e:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (2 ** attempt)
                                logger.warning(f"リクエストエラー: {str(e)}。{wait_time}秒後にリトライします。")
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error(f"最大リトライ回数に達しました: {str(e)}")
                                break
                except Exception as e:
                    logger.error(f"画像の読み込みに失敗: {str(e)}")
            except Empty:
                continue
            except Exception as e:
                logger.error(f"予期せぬエラー: {str(e)}")
                continue

    def stop(self):
        self.running = False

# comment_animation_improved.py の CommentOverlayWindow クラスを以下に置き換える

class CommentOverlayWindow(QWidget):
    def __init__(self, parent=None):
        # NOTE: WindowStaysOnTopHint を UI 設定で制御するため、ここでは常に付与しない。
        # 理由: ユーザーが「常に手前」をオフにしたときに即時反映できるようにする。
        super().__init__(parent, Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.8)
        # コメントや画像の設定値は、この初期サイズを基準とした論理サイズとして扱う。
        # ウィンドウの縦横比が変わっても収まるよう、短い側の倍率で一様に拡縮する。
        self.base_overlay_size = QSize(600, 800)
        self.display_scale = 1.0
        self.setGeometry(100, 100, 600, 800)

        # デフォルト設定を初期化
        self.settings = {
            "font_size": 31,
            "font_weight": 75,
            "font_shadow": 2,
            "font_color": "#FFFFFF",
            "font_family": "MS PGothic",
            "font_shadow_directions": ["bottom-right"],
            "font_shadow_color": "#000000",
            "comment_speed": 6.0,
            "display_position": "top",
            "max_comments": 80,
            "window_opacity": 0.8,
            "spacing": 30,
            "ng_ids": [],
            "ng_names": [],
            "ng_texts": [],
            "hide_anchor_comments": False,
            "hide_url_comments": False,
            "display_images": True,
            "hide_image_urls": True,
            "opaque_background_mode": False,
            "chroma_key_color": "#00FF00",
            "lock_overlay_aspect_ratio": True
        }

        self.comments = []
        self.max_comments = 80
        self.font_size = 31
        self.font_weight = 75
        self.font_shadow = 2
        self.font_color = QColor("#FFFFFF")
        self.font_family = "MS PGothic"
        self.font_shadow_directions = ["bottom-right"]
        self.font_shadow_color = QColor("#000000")
        self.comment_speed = 6.0
        self.display_position = "top"
        self.opaque_background_mode = False
        self.chroma_key_color = QColor("#00FF00")
        self.hide_anchor_comments = False
        self.hide_url_comments = False
        self.spacing = 30
        self.lock_overlay_aspect_ratio = True
        self.comment_queue = []
        self.comment_queue_max_size = 100

        self.comment_delay = 0
        self.delayed_comment_queue = []
        
        self.delay_processor = QTimer(self)
        self.delay_processor.timeout.connect(self.process_delayed_comments)
        self.delay_processor.start(100)

        self.flow_timer = QTimer(self)
        self.flow_timer.timeout.connect(self.flow_comment)
        self.flow_timer.start(200)

        self.current_batch_size = 0
        self.current_update_interval = 1.0

        self.move_area_height = 25
        self.close_button_size = 22
        self.minimize_button_size = 22
        self.maximize_button_size = 22  # 最大化ボタンのサイズ
        self.button_margin = 2
        self.is_hovering_close = False
        self.is_hovering_minimize = False
        self.is_hovering_maximize = False  # 最大化ボタンのホバー状態
        self.is_minimized = False
        self.is_maximized = False  # ウィンドウが最大化されているか
        self._normal_geometry = None  # 最大化前のジオメトリを保存

        self.calculate_comment_rows()
        self.row_usage = {}

        self.dragging = False
        self.resizing = False
        self.drag_position = QPoint()
        self.resize_border = 10
        self.resize_mode = None
        self.minimum_size = QSize(300, 200)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_comments)
        self.timer.start(8)

        self.comment_id_counter = 0
        self.setMouseTracking(True)
        # Hoverイベントを確実に受け取るためにWA_Hoverを有効化する
        # 意図: 一部環境でenter/leaveが期待通り発火しない場合があるため、
        #       明示的にホバー属性をセットして安定させる。
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # ホバー状態のフラグ: ウィンドウ内にマウスがいるかを追跡し、
        # フレーム（枠線／タイトル領域／ボタン）の表示制御に利用する。
        # 意図: ユーザーが操作していないときはフレームを隠して、
        # コメント描画を邪魔しないようにする。
        self.is_hovering_window = False
        self.main_window = None
        self.ng_ids = []
        self.ng_names = []
        self.ng_texts = []
        self.row_usage = {}
        self.my_comment_numbers = set()

        self.images = {}
        self.image_positions = {}
        self.movies = {}
        self.max_images = 5
        self.image_height = 300
        self.image_spacing = 40
        self.image_queue = []
        self.image_queue_timer = QTimer(self)
        self.image_queue_timer.timeout.connect(self.process_image_queue)
        self.image_queue_timer.start(100)

        self.image_loader_thread = None
        self.image_url_queue = Queue()
        self.pending_images = set()

        self.start_image_loader()

    def _update_display_scale(self):
        width_scale = self.width() / self.base_overlay_size.width()
        height_scale = self.height() / self.base_overlay_size.height()
        self.display_scale = max(0.01, min(width_scale, height_scale))

    def _scaled_value(self, value, minimum=1):
        return max(minimum, int(round(value * self.display_scale)))

    def _display_font(self):
        font = QFont(self.font_family)
        font.setPointSize(self._scaled_value(self.font_size))
        font.setWeight(self.font_weight)
        return font

    def _display_image_height(self):
        return self._scaled_value(self.image_height)

    def _comment_pixmap_inset(self, shadow_offset):
        # OBSなどが透過ウィンドウを取り込む際、境界上のアンチエイリアスが
        # 欠けないように影の幅とは別に安全余白を確保する。
        return shadow_offset + 2

    def _comment_y_position(self, row, line_height):
        if self.display_position == "top":
            y_position = self.move_area_height + row * self.row_height + line_height
        elif self.display_position == "bottom":
            y_position = self.height() - row * self.row_height - line_height
        else:
            y_position = (self.height() - line_height) // 2 + row * self.row_height
        return max(line_height + self.move_area_height,
                   min(y_position, self.height() - line_height))

    # ★★★【新設】事前レンダリング用のヘルパーメソッド ★★★
    def _create_comment_pixmap(self, text, font, font_color, shadow_color, shadow_offset, shadow_directions):
        """テキストと影を含むQPixmapを事前に生成する"""
        font_metrics = QFontMetrics(font)
        text_width = font_metrics.width(text)
        text_height = font_metrics.height()

        # 影とアンチエイリアスの安全余白を四辺に確保する。
        inset = self._comment_pixmap_inset(shadow_offset)
        pixmap_width = text_width + inset * 2
        pixmap_height = text_height + inset * 2
        
        pixmap = QPixmap(pixmap_width, pixmap_height)
        pixmap.fill(Qt.transparent)  # 透明な背景で初期化
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(font)
        
        # 最初に影を描画
        if shadow_offset > 0:
            painter.setPen(shadow_color)
            for direction in shadow_directions:
                dx = -shadow_offset if "left" in direction else shadow_offset
                dy = -shadow_offset if "top" in direction else shadow_offset
                painter.drawText(inset + dx,
                                 inset + dy + font_metrics.ascent(), text)

        # 最後に本体のテキストを描画
        painter.setPen(font_color)
        painter.drawText(inset, inset + font_metrics.ascent(), text)
        
        painter.end()
        return pixmap

    def add_my_comment(self, number, text):
        self.my_comment_numbers.add(number)
        logger.info(f"自分のコメントを登録: 番号={number}, テキスト={text}")
    
    def reset_my_comments(self):
        self.my_comment_numbers.clear()
        logger.info("自分のコメント番号をリセットしました")

    def add_comment_batch(self, comments):
        # (このメソッドは変更なし)
        batch_size = len(comments)
        self.current_batch_size = batch_size
        app = QApplication.instance()
        main_window = app.property("main_window")
        if main_window:
            self.current_update_interval = main_window.settings.get("update_interval", 1.0)
        else:
            self.current_update_interval = 1.0

        # 意図: 取得→表示までの遅延を最小化するため、キューが空の状態で
        #       新規バッチが来たら 1件目は schedule_next_comment の人為的待ち
        #       (calculate_flow_interval で 300-500ms) を経由せず即時表示する。
        was_queue_empty = not self.comment_queue

        comments_added_directly = 0
        for comment in comments:
            comment_timestamp = comment.get('timestamp')
            if self.comment_delay > 0 and comment_timestamp:
                display_time = comment_timestamp.timestamp() + self.comment_delay
                self.delayed_comment_queue.append((display_time, comment))
            else:
                self.comment_queue.append(comment)
                comments_added_directly += 1

        if self.delayed_comment_queue:
            self.delayed_comment_queue.sort(key=lambda x: x[0])

        if comments_added_directly > 0:
            if len(self.comment_queue) > self.comment_queue_max_size:
                excess = len(self.comment_queue) - self.comment_queue_max_size
                self.comment_queue = self.comment_queue[excess:]
                logger.warning(f"コメントキューが上限 {self.comment_queue_max_size} を超えたため、古いコメントを削除しました")

            if self.flow_timer.isActive():
                self.flow_timer.stop()

            # キューが直前まで空だった場合、1件目を即時に流して残りをスケジュール
            if was_queue_empty and self.comment_queue:
                first_comment = self.comment_queue.pop(0)
                self.add_comment(first_comment)
            self.schedule_next_comment()

    def process_delayed_comments(self):
        # (このメソッドは変更なし)
        if not self.delayed_comment_queue:
            return

        current_timestamp = time.time()
        
        num_ready = 0
        for display_time, comment in self.delayed_comment_queue:
            if current_timestamp >= display_time:
                num_ready += 1
            else:
                break

        if num_ready > 0:
            ready_comments = [comment for _, comment in self.delayed_comment_queue[:num_ready]]
            self.delayed_comment_queue = self.delayed_comment_queue[num_ready:]

            was_queue_empty = not self.comment_queue
            self.comment_queue.extend(ready_comments)
            logger.debug(f"{len(ready_comments)}件の遅延コメントをフローキューに追加。キュー長={len(self.comment_queue)}")

            if was_queue_empty:
                if self.flow_timer.isActive():
                    self.flow_timer.stop()
                self.schedule_next_comment()

    def schedule_next_comment(self):
        if self.comment_queue:
            interval = self.calculate_flow_interval()
            QTimer.singleShot(interval, self.flow_comment)
            logger.debug(f"次のコメントを {interval}ms 後にスケジュール")

    def calculate_flow_interval(self):
        """コメントのフロー間隔を計算（追いつき機能付き）
        
        キューが溜まっている場合は間隔を短縮して追いつく
        """
        queue_size = len(self.comment_queue)
        
        # キューサイズに応じて間隔を動的に短縮（追いつき機能）
        if queue_size > 50:
            # 大幅に遅延: 最速で流す
            logger.debug(f"追いつきモード(重度): キュー={queue_size}, 間隔=20ms")
            return 20
        elif queue_size > 30:
            # 中程度の遅延: かなり速く
            logger.debug(f"追いつきモード(中度): キュー={queue_size}, 間隔=50ms")
            return 50
        elif queue_size > 15:
            # 軽度の遅延: やや速く
            logger.debug(f"追いつきモード(軽度): キュー={queue_size}, 間隔=100ms")
            return 100
        
        # 通常時の処理
        if self.current_batch_size == 0 or self.current_update_interval <= 0:
            return 200

        comments_per_sec = self.current_batch_size / self.current_update_interval
        base_interval = int((self.current_update_interval * 1000) / self.current_batch_size)

        if comments_per_sec <= 2.0:
            return random.randint(300, 500)
        else:
            variance = int(base_interval * 0.2)
            lower_bound = max(50, base_interval - variance)
            upper_bound = min(500, base_interval + variance)
            start = min(lower_bound, upper_bound)
            end = max(lower_bound, upper_bound)
            logger.debug(f"Flow interval: base={base_interval}, variance={variance}, range=({start}, {end})")
            return random.randint(start, end)

    def adjust_flow_timer(self):
        # (このメソッドは変更なし)
        if self.current_batch_size == 0 or self.current_update_interval <= 0:
            self.flow_timer.setInterval(200)
            return

        comments_per_sec = self.current_batch_size / self.current_update_interval
        interval = int((self.current_update_interval * 1000) / self.current_batch_size)

        if comments_per_sec <= 2.0:
            interval = random.randint(300, 500)
        else:
            interval = max(50, min(500, interval))

        self.flow_timer.setInterval(interval)
        logger.info(f"flow_timer間隔を調整: {interval}ms (update_interval={self.current_update_interval}s, batch_size={self.current_batch_size})")

    def flow_comment(self):
        if not self.comment_queue:
            return

        queue_size = len(self.comment_queue)
        comments_to_flow = 1  # 通常は1件

        # 追いつきモード: キューサイズに応じて同時に流す件数を増やす
        if queue_size > 50:
            comments_to_flow = 5
        elif queue_size > 30:
            comments_to_flow = 4
        elif queue_size > 20:
            comments_to_flow = 3
        elif queue_size > 10:
            comments_to_flow = 2

        flowed_count = 0
        for _ in range(min(comments_to_flow, len(self.comment_queue))):
            comment = self.comment_queue.pop(0)
            self.add_comment(comment)
            flowed_count += 1
        
        if flowed_count > 1:
            logger.info(f"追いつきモード: {flowed_count}件のコメントを同時に流す, 残りキュー={len(self.comment_queue)}")
        else:
            logger.debug(f"コメントを流す: 残りキュー={len(self.comment_queue)}")
        
        self.schedule_next_comment()
            
    def add_system_message(self, message, message_type="generic"):
        font = self._display_font()
        font_metrics = QFontMetrics(font)
        
        text_width = font_metrics.width(message)
        row = self.find_available_row(text_width)
        
        line_height = font_metrics.height()
        y_position = self._comment_y_position(row, line_height)
        
        self.comment_id_counter += 1
        comment_id = f"system_{int(time.time()*1000)}_{self.comment_id_counter}"
        total_distance = self.width() + text_width
        speed = total_distance / self.comment_speed
        
        # Pixmapを生成
        comment_pixmap = self._create_comment_pixmap(
            message, font, self.font_color, self.font_shadow_color,
            self._scaled_value(self.font_shadow, 0), self.font_shadow_directions
        )
        
        comment_obj = CommentObject(
            id=comment_id,
            text=message,
            x=float(self.width()),
            y=y_position,
            width=text_width,
            height=line_height,
            row=row,
            creation_time=QApplication.instance().property("comment_time") or 0,
            speed=speed,
            is_system=True,
            pixmap=comment_pixmap
        )
        
        self.comments.append(comment_obj)
        self.row_usage[row] = comment_obj
        logger.info(f"システムメッセージ追加: {message}, 種別: {message_type}, ID: {comment_id}, row: {row}, y: {y_position}")
        self.update()

    def changeEvent(self, event):
        """ウィンドウ状態の変化を監視し、最小化/復元フラグを同期する"""
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                logger.info("WindowStateChange: minimized (OS level)")
                self.is_minimized = True
            else:
                if self.is_minimized:
                    logger.info("WindowStateChange: restored from minimized")
                self.is_minimized = False
            self.update()
        super().changeEvent(event)

    # ... (calculate_comment_rowsからresize_windowまでのメソッドは変更なし) ...
    def calculate_comment_rows(self):
        font = self._display_font()
        font_metrics = QFontMetrics(font)
        
        line_height = font_metrics.height()
        self.row_height = line_height + self._scaled_value(self.spacing, 0)
        
        available_height = self.height() - self.move_area_height - line_height
        
        if self.row_height > 0:
            self.max_rows = max(1, available_height // self.row_height + 1)
        else:
            self.max_rows = 1

    def resizeEvent(self, event):
        super().resizeEvent(event)
        old_size = event.oldSize()
        self._update_display_scale()
        self.calculate_comment_rows()
        if old_size.isValid() and old_size.width() > 0 and old_size.height() > 0:
            self._rescale_flowing_objects(old_size)

    def _rescale_flowing_objects(self, old_size):
        """表示中のコメント・画像を、新しいオーバーレイ倍率へ追従させる。"""
        font = self._display_font()
        font_metrics = QFontMetrics(font)
        line_height = font_metrics.height()
        shadow = self._scaled_value(self.font_shadow, 0)
        old_width = old_size.width()
        new_width = self.width()

        self.row_usage.clear()
        for comment in self.comments:
            old_object_width = max(1, comment.width)
            progress = (old_width - comment.x) / max(1, old_width + old_object_width)

            comment.pixmap = self._create_comment_pixmap(
                comment.text, font, self.font_color, self.font_shadow_color,
                shadow, self.font_shadow_directions
            )
            comment.width = font_metrics.width(comment.text)
            comment.height = line_height
            comment.row = comment.row % self.max_rows
            comment.x = new_width - progress * (new_width + comment.width)
            comment.y = self._comment_y_position(comment.row, line_height)
            comment.speed = (new_width + comment.width) / self.comment_speed

            current = self.row_usage.get(comment.row)
            if current is None or comment.x > current.x:
                self.row_usage[comment.row] = comment

        image_height = self._display_image_height()
        bottom_margin = self._scaled_value(10)
        for image_id, pos in self.image_positions.items():
            old_object_width = max(1, pos['width'])
            progress = (old_width - pos['x']) / max(1, old_width + old_object_width)
            aspect_ratio = pos['width'] / max(1, pos['height'])
            pos['height'] = image_height
            pos['width'] = max(1, int(round(image_height * aspect_ratio)))
            pos['x'] = new_width - progress * (new_width + pos['width'])
            pos['y'] = self.height() - image_height - bottom_margin
            pos['speed'] = (new_width + pos['width']) / self.comment_speed

            movie = self.movies.get(image_id)
            if movie:
                movie.setScaledSize(QSize(pos['width'], pos['height']))

        self.update()

    def update_cursor(self, pos):
        if self.is_minimized:
            self.setCursor(Qt.ArrowCursor)
            self.resize_mode = None
            return

        left = pos.x() <= self.resize_border
        right = pos.x() >= self.width() - self.resize_border
        top = pos.y() <= self.resize_border
        bottom = pos.y() >= self.height() - self.resize_border
        in_move_area = pos.y() <= self.move_area_height
        # トップバー（move_area_height）内にマウスがいるときだけホバー扱いにする
        # 意図: 枠の「中身」ではホバー扱いにしないため、ここでフラグを更新する
        self.is_hovering_window = in_move_area

        close_button_rect = QRect(
            self.width() - self.close_button_size - self.button_margin,
            self.button_margin,
            self.close_button_size,
            self.close_button_size
        )
        # 最大化ボタンは閉じるボタンと枠透明化ボタンの間
        maximize_button_rect = QRect(
            self.width() - self.close_button_size - self.maximize_button_size - self.button_margin * 3,
            self.button_margin,
            self.maximize_button_size,
            self.maximize_button_size
        )
        minimize_button_rect = QRect(
            self.width() - self.close_button_size - self.maximize_button_size - self.minimize_button_size - self.button_margin * 5,
            self.button_margin,
            self.minimize_button_size,
            self.minimize_button_size
        )

        self.is_hovering_close = close_button_rect.contains(pos)
        self.is_hovering_maximize = maximize_button_rect.contains(pos)
        self.is_hovering_minimize = minimize_button_rect.contains(pos)
        self.is_hovering_maximize = maximize_button_rect.contains(pos)
        if self.is_hovering_close:
            self.setCursor(Qt.PointingHandCursor)
            self.resize_mode = None
        elif self.is_hovering_maximize:
            self.setCursor(Qt.PointingHandCursor)
            self.resize_mode = None
        elif self.is_hovering_minimize:
            self.setCursor(Qt.PointingHandCursor)
            self.resize_mode = None
        elif self.is_hovering_maximize:
            self.setCursor(Qt.PointingHandCursor)
            self.resize_mode = None
        elif in_move_area and not (left or right):
            self.setCursor(Qt.OpenHandCursor)
            self.resize_mode = None
        elif left and top:
            self.setCursor(Qt.SizeFDiagCursor)
            self.resize_mode = "top-left"
        elif right and bottom:
            self.setCursor(Qt.SizeFDiagCursor)
            self.resize_mode = "bottom-right"
        elif left and bottom:
            self.setCursor(Qt.SizeBDiagCursor)
            self.resize_mode = "bottom-left"
        elif right and top:
            self.setCursor(Qt.SizeBDiagCursor)
            self.resize_mode = "top-right"
        elif left:
            self.setCursor(Qt.SizeHorCursor)
            self.resize_mode = "left"
        elif right:
            self.setCursor(Qt.SizeHorCursor)
            self.resize_mode = "right"
        elif top:
            self.setCursor(Qt.SizeVerCursor)
            self.resize_mode = "top"
        elif bottom:
            self.setCursor(Qt.SizeVerCursor)
            self.resize_mode = "bottom"
        else:
            self.setCursor(Qt.ArrowCursor)
            self.resize_mode = None

        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            self.update_cursor(pos)

            # 最小化状態では通常のクリックを無視するが、
            # タイトルバー（move_area_height）をクリックした場合は復元する。
            # 理由: ユーザーが最小化後に元に戻せず操作不能になる問題を防ぐため。
            if self.is_minimized:
                if pos.y() <= self.move_area_height:
                    logger.info("Minimized: restoring window on titlebar click")
                    # OSレベルで最小化されている場合に備え、正しく復元する
                    try:
                        self.showNormal()
                    except Exception:
                        pass
                    self.is_minimized = False
                    self.update()
                    return
                return

            close_button_rect = QRect(
                self.width() - self.close_button_size - self.button_margin,
                self.button_margin,
                self.close_button_size,
                self.close_button_size
            )
            # 最大化ボタンは閉じるボタンと枠透明化ボタンの間
            maximize_button_rect = QRect(
                self.width() - self.close_button_size - self.maximize_button_size - self.button_margin * 3,
                self.button_margin,
                self.maximize_button_size,
                self.maximize_button_size
            )
            minimize_button_rect = QRect(
                self.width() - self.close_button_size - self.maximize_button_size - self.minimize_button_size - self.button_margin * 5,
                self.button_margin,
                self.minimize_button_size,
                self.minimize_button_size
            )

            if close_button_rect.contains(pos):
                logger.info("Close button clicked, closing window")
                self.close()
            elif maximize_button_rect.contains(pos):
                self.toggle_maximize(event.globalPos())
            elif minimize_button_rect.contains(pos):
                logger.info("Minimize button clicked, performing OS minimize")
                # OS レベルの最小化を行い、内部フラグも立てる
                try:
                    self.showMinimized()
                except Exception:
                    # showMinimized が利用できない環境では代替で非表示にする
                    self.hide()
                self.is_minimized = True
                self.update()
            elif pos.y() <= self.move_area_height and self.resize_mode is None:
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                logger.info("Move area drag started")
            elif self.resize_mode is not None:
                self.resizing = True
                self.drag_position = event.globalPos()
                logger.info(f"Resize started: mode={self.resize_mode}")
                self.update()
    
    def _screen_geometry_for_position(self, global_pos=None):
        """操作位置が属するディスプレイの、タスクバーを含む画面領域を返す。"""
        desktop = QApplication.desktop()
        if global_pos is None:
            global_pos = self.mapToGlobal(self.rect().center())

        # ウィンドウの中心ではなくクリック位置を使う意図: 複数ディスプレイ間に
        # またがっているウィンドウでも、ユーザーが操作した画面で最大化するため。
        screen_number = desktop.screenNumber(global_pos)
        if screen_number < 0:
            screen_number = desktop.screenNumber(self)
        return desktop.screenGeometry(screen_number)

    def toggle_maximize(self, global_pos=None):
        """ウィンドウの最大化/元のサイズへの切り替え"""
        if self.is_maximized:
            # 元のサイズに戻す
            if self._normal_geometry:
                self.setGeometry(self._normal_geometry)
                logger.info(f"Restored window to normal size: {self._normal_geometry}")
            self.is_maximized = False
        else:
            # 現在のジオメトリを保存
            self._normal_geometry = self.geometry()

            # クリックされた位置のモニターで最大化する。
            screen_geometry = self._screen_geometry_for_position(global_pos)
            self.setGeometry(screen_geometry)
            self.is_maximized = True
            logger.info(f"Maximized window on the operation screen: {screen_geometry}")
        
        # 状態を即時保存
        app = QApplication.instance()
        main_window = app.property("main_window")
        if main_window:
            main_window.save_window_position(
                self.pos().x(), self.pos().y(), self.width(), self.height(),
                is_maximized=self.is_maximized,
                normal_geometry=self._normal_geometry
            )
        
        self.update()

    def mouseDoubleClickEvent(self, event):
        """タイトルバー（ハンドル）のダブルクリックで最大化/元に戻す"""
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            # タイトルバー領域内かつ最小化状態でない場合
            if pos.y() <= self.move_area_height and not self.is_minimized:
                # ボタン領域を除外
                button_area_start = self.width() - self.close_button_size - self.maximize_button_size - self.minimize_button_size - self.button_margin * 5
                if pos.x() < button_area_start:
                    if self.is_maximized:
                        self.toggle_maximize(event.globalPos())
                    else:
                        self.toggle_maximize(event.globalPos())

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self.dragging:
            self.move(event.globalPos() - self.drag_position)
            logger.debug(f"Dragging: new pos=({self.x()}, {self.y()})")
        elif self.resizing:
            self.resize_window(event.globalPos())
            logger.debug(f"Resizing: size=({self.width()}, {self.height()})")
        else:
            self.update_cursor(pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.dragging or self.resizing:
                logger.info("Move or resize ended")
                app = QApplication.instance()
                main_window = app.property("main_window")
                if main_window:
                    main_window.save_window_position(self.pos().x(), self.pos().y(), self.width(), self.height())
            self.dragging = False
            self.resizing = False
            self.update_cursor(event.pos())

    def enterEvent(self, event):
        # ウィンドウ内にマウスが入った（ホバー開始）ことを検知して
        # フレーム表示を有効化する。
        # 意図: マウスがウィンドウ内にあるときだけ枠／ボタンを表示し、
        # 操作していないときはフレームを隠して視認性を向上させる。
        # マウスがウィンドウに入った時点で、現在のカーソル位置が
        # トップバー内かどうかを判定してフラグを設定する。
        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        self.is_hovering_window = local_pos.y() <= self.move_area_height
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # マウスがウィンドウから離れた（ホバー終了）のでフレーム表示を無効化する。
        # ウィンドウを離れたら必ずホバーフラグを解除する
        self.is_hovering_window = False
        self.update()
        super().leaveEvent(event)

    def closeEvent(self, event):
        for movie in self.movies.values():
            movie.stop()
        self.stop_image_loader()
        self.image_queue_timer.stop()
        app = QApplication.instance()
        main_window = app.property("main_window")
        if main_window:
            main_window.save_window_position(
                self.pos().x(), self.pos().y(), self.width(), self.height(),
                is_maximized=self.is_maximized,
                normal_geometry=self._normal_geometry
            )
        event.accept()

    def resize_window(self, global_pos):
        if self.resize_mode is None:
            return

        delta = global_pos - self.drag_position
        geo = self.geometry()
        new_x = geo.x()
        new_y = geo.y()
        new_width = geo.width()
        new_height = geo.height()

        if "left" in self.resize_mode:
            new_x += delta.x()
            new_width -= delta.x()
        elif "right" in self.resize_mode:
            new_width += delta.x()

        if "top" in self.resize_mode:
            new_y += delta.y()
            new_height -= delta.y()
        elif "bottom" in self.resize_mode:
            new_height += delta.y()

        if self.lock_overlay_aspect_ratio:
            aspect_ratio = 16 / 9
            minimum_width = max(self.minimum_size.width(), int(round(self.minimum_size.height() * aspect_ratio)))
            minimum_height = max(self.minimum_size.height(), int(round(self.minimum_size.width() / aspect_ratio)))
            has_horizontal_handle = "left" in self.resize_mode or "right" in self.resize_mode
            has_vertical_handle = "top" in self.resize_mode or "bottom" in self.resize_mode

            # 四隅の操作では、より大きく動かした軸を基準にする。
            use_width = has_horizontal_handle and (
                not has_vertical_handle or abs(delta.x()) >= abs(delta.y()) * aspect_ratio
            )
            if use_width:
                new_width = max(minimum_width, new_width)
                new_height = max(minimum_height, int(round(new_width / aspect_ratio)))
                if "left" in self.resize_mode:
                    new_x = geo.x() + geo.width() - new_width
                if "top" in self.resize_mode:
                    new_y = geo.y() + geo.height() - new_height
                elif not has_vertical_handle:
                    new_y = geo.y() + (geo.height() - new_height) // 2
            else:
                new_height = max(minimum_height, new_height)
                new_width = max(minimum_width, int(round(new_height * aspect_ratio)))
                if "top" in self.resize_mode:
                    new_y = geo.y() + geo.height() - new_height
                if "left" in self.resize_mode:
                    new_x = geo.x() + geo.width() - new_width
                elif not has_horizontal_handle:
                    new_x = geo.x() + (geo.width() - new_width) // 2
        else:
            new_width = max(self.minimum_size.width(), new_width)
            new_height = max(self.minimum_size.height(), new_height)

        self.setGeometry(new_x, new_y, new_width, new_height)
        self.drag_position = global_pos

        self.update()

    def _check_collision(self, speed_new, existing_comment):
        if not existing_comment:
            return True

        # ★★★ 変更点 ★★★
        right_edge = existing_comment.x + existing_comment.width
        current_speed = existing_comment.speed
        gap = self.width() - right_edge

        if gap < self._scaled_value(120):
            return False

        if speed_new > current_speed:
            relative_speed = speed_new - current_speed
            time_to_catch = gap / relative_speed
            if time_to_catch < 2.0:
                return False
        
        return True

    def find_available_row(self, comment_width):
        speed_new = (self.width() + comment_width) / self.comment_speed

        available_rows = []
        for r in range(self.max_rows):
            if r not in self.row_usage:
                available_rows.append(r)
            else:
                if self._check_collision(speed_new, self.row_usage.get(r)):
                    available_rows.append(r)
        
        if available_rows:
            return min(available_rows)

        for r in range(self.max_rows - 1):
            if r in self.row_usage and (r + 1) in self.row_usage:
                is_slot_occupied = False
                for key in self.row_usage.keys():
                    if isinstance(key, float) and r < key < r + 1:
                        if not self._check_collision(speed_new, self.row_usage[key]):
                            is_slot_occupied = True
                            break
                
                if not is_slot_occupied:
                    random_offset = random.uniform(0.3, 0.7)
                    return r + random_offset

        if self.row_usage:
            return min(self.row_usage.keys(), key=lambda k: self.row_usage[k].x + self.row_usage[k].width)
        
        return 0
    
    def extract_image_url(self, text):
        image_extensions = r'\.(jpg|jpeg|png|gif|webp)'
        
        imgur_pattern = r'https?://(?:i\.)?imgur\.com/([a-zA-Z0-9]+)(?:\.[a-zA-Z]+)?'
        imgur_matches = re.findall(imgur_pattern, text)
        if imgur_matches:
            urls = []
            for image_id in imgur_matches[:5]:
                original_url = next((url for url in re.findall(r'https?://[^\s<>"]+', text) 
                                   if image_id in url), None)
                if original_url and re.search(image_extensions, original_url, re.IGNORECASE):
                    urls.append(original_url)
                else:
                    urls.append(f"https://i.imgur.com/{image_id}.jpg")
                logger.info(f"imgur URLを検出: {urls[-1]}")
            return urls
        
        url_pattern = r'https?://[^\s<>"]+'
        urls = re.findall(url_pattern, text)
        
        image_urls = []
        for url in urls:
            if re.search(image_extensions, url, re.IGNORECASE):
                image_urls.append(url)
                logger.info(f"画像URLを検出: {url}")
                if len(image_urls) >= 5:
                    break
        
        return image_urls if image_urls else None

    def start_image_loader(self):
        if not self.image_loader_thread:
            logger.info("画像読み込みスレッドを開始します")
            self.image_loader_thread = ImageLoaderThread(self.image_url_queue)
            self.image_loader_thread.image_loaded.connect(self.handle_loaded_image)
            self.image_loader_thread.start()
            logger.info("画像読み込みスレッドが開始されました")

    def stop_image_loader(self):
        if self.image_loader_thread:
            self.image_loader_thread.stop()
            self.image_loader_thread.wait()
            self.image_loader_thread = None

    def handle_loaded_image(self, url, content_bytes, comment_id, content_type):
        logger.info(f"画像のデータ受信を検知: URL={url}")
        if url in self.pending_images:
            self.pending_images.remove(url)
            if content_bytes:
                is_gif = 'image/gif' in content_type

                if is_gif:
                    logger.debug(f"GIFデータを処理: {url}")
                    try:
                        buffer = QBuffer()
                        buffer.setData(QByteArray(content_bytes))
                        buffer.open(QBuffer.ReadOnly)
                        
                        movie = QMovie()
                        movie.setDevice(buffer)
                        
                        temp_image = QImage()
                        temp_image.loadFromData(content_bytes)
                        if temp_image.isNull():
                             logger.error(f"GIFの画像データが無効: {url}")
                             return

                        image_height = self._display_image_height()
                        movie.setScaledSize(QSize(
                            int(image_height * (temp_image.width() / temp_image.height())),
                            image_height
                        ))
                        
                        if not movie.isValid():
                            logger.error(f"GIFアニメーションが無効: {url}")
                            return
                        movie.start()
                        movie.buffer = buffer
                        image_id = f"img_{int(time.time()*1000)}_{len(self.images)}"
                        self.image_queue.append((image_id, movie, comment_id))
                        logger.info(f"GIFアニメーションをキューに追加: ID={image_id}, URL={url}")
                    except Exception as e:
                        logger.error(f"GIFアニメーションの処理中にエラー: {str(e)}")
                else:
                    image = QImage()
                    if image.loadFromData(content_bytes):
                        image_id = f"img_{int(time.time()*1000)}_{len(self.images)}"
                        # 元画像を保持し、描画時に現在のオーバーレイ倍率へ合わせる。
                        self.image_queue.append((image_id, image, comment_id))
                        logger.info(f"画像をキューに追加: ID={image_id}, URL={url}")
                    else:
                        logger.error(f"静止画データの読み込みに失敗: URL={url}")
            else:
                logger.error(f"画像データの受信に失敗: URL={url}")
        else:
            logger.warning(f"待機中の画像リストにURLが見つかりません: {url}")

    def process_image_queue(self):
        if not self.image_queue:
            return

        window_width = self.width()
        image_height = self._display_image_height()
        logger.debug(f"画像キュー処理開始: キューサイズ={len(self.image_queue)}, ウィンドウ幅={window_width}")

        processed_ids = set()
        for image_data in self.image_queue[:]:
            if len(image_data) != 3:
                continue
            image_id, image, comment_id = image_data
            if image_id in processed_ids or image_id in self.image_positions:
                continue
            processed_ids.add(image_id)

            if image:
                logger.debug(f"画像処理開始: ID={image_id}, comment_id={comment_id}, タイプ={type(image)}")
                if isinstance(image, QMovie):
                    current_size = image.scaledSize()
                    aspect_ratio = current_size.width() / max(1, current_size.height())
                    scaled_width = max(1, int(round(image_height * aspect_ratio)))
                    image.setScaledSize(QSize(scaled_width, image_height))
                    self.movies[image_id] = image
                else:
                    scaled_width = max(1, int(round(image_height * (image.width() / image.height()))))
                    self.images[image_id] = image

                start_x = window_width
                min_gap = self._scaled_value(60)

                prev_images = [pos for img_id, pos in self.image_positions.items() if pos.get('comment_id') == comment_id]
                if prev_images:
                    prev_pos = max(prev_images, key=lambda p: p['x'] + p['width'])
                    prev_x = prev_pos['x']
                    prev_width = prev_pos['width']
                    logger.debug(f"前の画像検出: prev_x={prev_x}, prev_width={prev_width}, comment_id={comment_id}")
                    if prev_x + prev_width + min_gap > window_width:
                        start_x = prev_x + prev_width + min_gap
                        logger.debug(f"次の画像の開始位置を調整: start_x={start_x}")
                        if start_x >= window_width:
                            logger.debug(f"画面外のため保留: start_x={start_x}")
                            continue

                self.image_positions[image_id] = {
                    'x': start_x,
                    'y': self.height() - image_height - self._scaled_value(10),
                    'width': scaled_width,
                    'height': image_height,
                    'speed': (window_width + scaled_width) / self.comment_speed,
                    'comment_id': comment_id
                }
                logger.info(f"画像を表示: ID={image_id}, x={start_x}, comment_id={comment_id}")
                self.image_queue.remove(image_data)
                self.update()

        while len(self.images) + len(self.movies) > self.max_images:
            oldest_id = min(self.images.keys() if self.images else self.movies.keys())
            if oldest_id in self.images:
                del self.images[oldest_id]
            if oldest_id in self.movies:
                self.movies[oldest_id].stop()
                del self.movies[oldest_id]
            if oldest_id in self.image_positions:
                del self.image_positions[oldest_id]
            logger.info(f"古い画像を削除: ID={oldest_id}")

    def load_image(self, url, comment_id=None):
        if url in self.pending_images:
            return None

        logger.info(f"画像読み込みを開始: {url}")
        self.pending_images.add(url)
        self.image_url_queue.put((url, comment_id))
        return None

    def update_comments(self):
        current_time = QApplication.instance().property("comment_time") or 0
        to_remove = []
        
        processed_ids = set()
        for comment in self.comments[:]:
            # ★★★ 変更点 ★★★
            if comment.id in processed_ids:
                continue
            processed_ids.add(comment.id)
            
            elapsed = current_time - comment.creation_time
            comment.x -= comment.speed * (8 / 1000.0)
            if comment.x < -comment.width:
                to_remove.append(comment.id)
        
        for comment_id in to_remove:
            # ★★★ 変更点 ★★★
            self.comments = [c for c in self.comments if c.id != comment_id]
            for row, comment in list(self.row_usage.items()):
                if comment.id == comment_id:
                    del self.row_usage[row]
                    break

        to_remove_images = []
        for image_id, pos in self.image_positions.items():
            pos['x'] -= pos['speed'] * (8 / 1000.0)
            if pos['x'] + pos['width'] < 0:
                to_remove_images.append(image_id)

        for image_id in to_remove_images:
            if image_id in self.images:
                del self.images[image_id]
            if image_id in self.movies:
                self.movies[image_id].stop()
                del self.movies[image_id]
            if image_id in self.image_positions:
                del self.image_positions[image_id]
        
        self.update()

    # ★★★【修正】add_commentでPixmapを生成するように変更 ★★★
    def add_comment(self, comment):
        text = comment['text']
        name = comment['name']
        user_id = comment['id']
        
        # ... (NGフィルタリング、URL/アンカー非表示処理は変更なし) ...
        if user_id in self.ng_ids: return
        if any(ng_name in name for ng_name in self.ng_names): return
        if any(ng_text in text for ng_text in self.ng_texts): return
        if self.hide_anchor_comments and ">>" in text: return
        
        display_text = text
        image_urls = self.extract_image_url(text)
        if image_urls and self.settings.get("hide_image_urls", True):
            for url in image_urls:
                display_text = display_text.replace(url, "").strip()
            if display_text:
                display_text = f"[📷] {display_text}"
            else:
                display_text = ""
        
        if self.hide_url_comments and "http" in display_text : return

        if self.settings.get("display_images", True) and image_urls:
            self.comment_id_counter += 1
            comment_id = f"comment_{int(time.time()*1000)}_{self.comment_id_counter}"
            for image_url in image_urls:
                self.load_image(image_url, comment_id)
        
        if not display_text:
            return

        if len(self.comments) >= self.max_comments:
            self.remove_oldest_comment()
        
        font = self._display_font()
        font_metrics = QFontMetrics(font)
        
        text_width = font_metrics.width(display_text)
        row = self.find_available_row(text_width)
        
        line_height = font_metrics.height()
        y_position = self._comment_y_position(row, line_height)
        
        # Pixmapを生成
        comment_pixmap = self._create_comment_pixmap(
            display_text, font, self.font_color, self.font_shadow_color,
            self._scaled_value(self.font_shadow, 0), self.font_shadow_directions
        )
        
        self.comment_id_counter += 1
        comment_id = f"comment_{int(time.time()*1000)}_{self.comment_id_counter}"
        total_distance = self.width() + text_width
        speed = total_distance / self.comment_speed
        
        comment_obj = CommentObject(
            id=comment_id,
            text=display_text,
            x=float(self.width()),
            y=y_position,
            width=text_width,
            height=line_height,
            row=row,
            creation_time=QApplication.instance().property("comment_time") or 0,
            speed=speed,
            number=comment.get('number', 0),
            pixmap=comment_pixmap
        )
        self.comments.append(comment_obj)
        self.row_usage[row] = comment_obj
        # ★★★ 変更点: ['number'] を .number に修正 ★★★
        logger.info(f"コメント追加: 番号={comment_obj.number}, テキスト={display_text}, 元テキスト={text}, ID={comment_id}")
        self.update()

    def update_settings(self, settings):
        self.settings = settings.copy()
        self.font_size = self.settings.get("font_size", self.font_size)
        self.font_weight = self.settings.get("font_weight", self.font_weight)
        self.font_shadow = self.settings.get("font_shadow", self.font_shadow)
        self.font_color = QColor(self.settings.get("font_color", self.font_color.name()))
        self.font_family = self.settings.get("font_family", self.font_family)
        self.font_shadow_directions = self.settings.get("font_shadow_directions", ["bottom-right"])
        self.font_shadow_color = QColor(self.settings.get("font_shadow_color", self.font_shadow_color.name()))
        self.comment_speed = self.settings.get("comment_speed", self.comment_speed)
        self.display_position = self.settings.get("display_position", "top")
        self.max_comments = self.settings.get("max_comments", self.max_comments)
        self.hide_anchor_comments = self.settings.get("hide_anchor_comments", self.hide_anchor_comments)
        self.hide_url_comments = self.settings.get("hide_url_comments", self.hide_url_comments)
        self.spacing = self.settings.get("spacing", self.spacing)
        self.ng_ids = self.settings.get("ng_ids", [])
        self.ng_names = self.settings.get("ng_names", [])
        self.ng_texts = self.settings.get("ng_texts", [])
        self.current_update_interval = self.settings.get("update_interval", 1.0)

        self.comment_delay = self.settings.get("comment_delay", 0)
        self.lock_overlay_aspect_ratio = self.settings.get("lock_overlay_aspect_ratio", True)
        self.opaque_background_mode = self.settings.get("opaque_background_mode", False)
        self.chroma_key_color = QColor(self.settings.get("chroma_key_color", "#00FF00"))
        
        opacity = self.settings.get("window_opacity", 0.8)
        # 意図: クロマキー向け単色背景では半透明合成を避け、色抜きしやすい不透明表示に固定する。
        target_opacity = 1.0 if self.opaque_background_mode else opacity
        if abs(self.windowOpacity() - target_opacity) > 0.001:
            self.setWindowOpacity(target_opacity)

        target_translucent = not self.opaque_background_mode
        if self.testAttribute(Qt.WA_TranslucentBackground) != target_translucent:
            # WindowsのLayered Windowは表示中に透明属性を切り替えると、
            # UpdateLayeredWindowIndirectへ不整合なサイズ/描画領域が渡されることがある。
            # 属性が実際に変わる場合だけ一度隠してから切り替え、通常の設定変更では
            # 半透明ウィンドウのネイティブ再構成を発生させない。
            was_visible = self.isVisible()
            if was_visible:
                self.hide()
            self.setAttribute(Qt.WA_TranslucentBackground, target_translucent)
            if was_visible:
                self.show()
        
        self.calculate_comment_rows()
        self._rescale_flowing_objects(self.size())
        
        logger.debug(f"update_settings 実行後 - display_images: {self.settings.get('display_images', True)}, hide_image_urls: {self.settings.get('hide_image_urls', True)}")
        self.update()

    def remove_oldest_comment(self):
        if not self.comments:
            return
        
        # ★★★ 変更点 ★★★
        oldest_comment = min(self.comments, key=lambda c: c.creation_time)
        logger.info(f"上限超過で削除: ID={oldest_comment.id}, x={oldest_comment.x:.1f}, text={oldest_comment.text}")
        self.comments.remove(oldest_comment)
        if oldest_comment.row in self.row_usage:
            self.row_usage.pop(oldest_comment.row)

    # ★★★【修正】paintEventをPixmap描画ベースに全面的に書き換え ★★★
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 意図: OBSのクロマキー抜き向けに、背景を単色で全面塗りするモードを提供する。
        if self.opaque_background_mode:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.chroma_key_color))
            painter.drawRect(self.rect())

        # フォントメトリクスは枠線描画用に一度だけ取得
        font = self._display_font()
        font_metrics = QFontMetrics(font)

        # --- ウィンドウのコントロールUI描画（ホバー/ドラッグ時のみ） ---
        # フレーム（タイトル領域・枠線・ボタン）は、ホバー・ドラッグ・リサイズ時のみ表示する
        # 意図: 常時フレームを表示すると視認性が悪くなるため、操作時だけ表示する
        show_frame = (not self.is_minimized) and (self.is_hovering_window or self.dragging or self.resizing)

        # フレーム非表示時は「上部バーの領域だけ」にほぼ透過の描画を入れる。
        # 意図: 全画面に当たり判定を持たせると中身がクリックを奪うため、
        #       ホバー/ドラッグを受ける領域を上部バーだけに限定する。
        if not show_frame:
            if self.opaque_background_mode:
                painter.setBrush(QBrush(self.chroma_key_color))
            else:
                painter.setBrush(QBrush(QColor(0, 0, 0, 1)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(0, 0, self.width(), self.move_area_height)

        if show_frame:
            # ... (この部分は元のコードのまま) ...
            painter.setBrush(QBrush(QColor(50, 50, 50, 100)))
            painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
            painter.drawRect(0, 0, self.width(), self.move_area_height)

            close_button_x = self.width() - self.close_button_size - self.button_margin
            close_button_y = self.button_margin
            if self.is_hovering_close: painter.setPen(QPen(QColor(230, 230, 230, 200), 2))
            else: painter.setPen(QPen(QColor(230, 230, 230, 150), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(close_button_x + 6, close_button_y + 6, close_button_x + self.close_button_size - 6, close_button_y + self.close_button_size - 6)
            painter.drawLine(close_button_x + self.close_button_size - 6, close_button_y + 6, close_button_x + 6, close_button_y + self.close_button_size - 6)

            # 最大化ボタン（四角マーク）を閉じるボタンの左側に描画
            maximize_button_x = self.width() - self.close_button_size - self.maximize_button_size - self.button_margin * 3
            maximize_button_y = self.button_margin
            if self.is_hovering_maximize: painter.setPen(QPen(QColor(230, 230, 230, 200), 2))
            else: painter.setPen(QPen(QColor(230, 230, 230, 150), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(maximize_button_x + 5, maximize_button_y + 5, self.maximize_button_size - 10, self.maximize_button_size - 10)

            # 枠透明化ボタン（−マーク）を最大化ボタンの左側に描画
            minimize_button_x = self.width() - self.close_button_size - self.maximize_button_size - self.minimize_button_size - self.button_margin * 5
            minimize_button_y = self.button_margin
            if self.is_hovering_minimize: painter.setPen(QPen(QColor(230, 230, 230, 200), 2))
            else: painter.setPen(QPen(QColor(230, 230, 230, 150), 2))
            painter.drawLine(minimize_button_x + 6, minimize_button_y + self.minimize_button_size // 2, minimize_button_x + self.minimize_button_size - 6, minimize_button_y + self.minimize_button_size // 2)

            painter.setBrush(QBrush(QColor(0, 0, 0, 1)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(0, 0, self.resize_border, self.height())
            painter.drawRect(self.width() - self.resize_border, 0, self.resize_border, self.height())
            painter.drawRect(0, 0, self.width(), self.resize_border)
            painter.drawRect(0, self.height() - self.resize_border, self.width(), self.resize_border)

            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(100, 100, 100, 150), 1))
            painter.drawRect(0, 0, 1, self.height())
            painter.drawRect(self.width() - 1, 0, 1, self.height())
            painter.drawRect(0, 0, self.width(), 1)
            painter.drawRect(0, self.height() - 1, self.width(), 1)

        # --- 画像/GIFの描画 (変更なし) ---
        for image_id, image in self.images.items():
            if image_id in self.image_positions:
                pos = self.image_positions[image_id]
                if not image.isNull():
                    target = QRect(int(pos['x']), int(pos['y']), pos['width'], pos['height'])
                    painter.drawImage(target, image)
        for image_id, movie in self.movies.items():
            if image_id in self.image_positions:
                pos = self.image_positions[image_id]
                if movie.isValid():
                    current_image = movie.currentImage()
                    if not current_image.isNull():
                        target = QRect(int(pos['x']), int(pos['y']), pos['width'], pos['height'])
                        painter.drawImage(target, current_image)

        # --- コメントの描画 (Pixmapベースに書き換え) ---
        highlight_padding = self._scaled_value(5)
        highlight_size_extra = highlight_padding * 2
        highlight_pen_width = self._scaled_value(3)
        for comment in self.comments:
            # ★★★ 変更点: getattrを使用し、より安全に属性にアクセス ★★★
            pixmap = getattr(comment, 'pixmap', None)
            if not pixmap or comment.x + comment.width < 0 or comment.x > self.width():
                continue

            # 枠線や背景の描画ロジックは維持
            is_system = getattr(comment, 'is_system', False)
            is_my_comment = False
            is_anchored_to_my_comment = False

            if not is_system:
                is_my_comment = comment.number in self.my_comment_numbers
                if not is_my_comment:
                    anchor_matches = re.findall(r'>>([0-9]+)', comment.text)
                    for anchor in anchor_matches:
                        if int(anchor) in self.my_comment_numbers:
                            is_anchored_to_my_comment = True
                            break
            
            # 枠線/背景の描画 (★★★ 変更点 ★★★)
            if is_system:
                painter.setBrush(QBrush(QColor(255, 255, 0, 70)))
                painter.setPen(Qt.NoPen)
                painter.drawRect(int(comment.x) - highlight_padding,
                                int(comment.y) - font_metrics.ascent() - highlight_padding,
                                comment.width + highlight_size_extra,
                                comment.height + highlight_size_extra)
            elif is_my_comment:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 0, 255), highlight_pen_width))
                painter.drawRect(int(comment.x) - highlight_padding,
                                int(comment.y) - font_metrics.ascent() - highlight_padding,
                                comment.width + highlight_size_extra,
                                comment.height + highlight_size_extra)
            elif is_anchored_to_my_comment:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 0, 0, 255), highlight_pen_width))
                painter.drawRect(int(comment.x) - highlight_padding,
                                int(comment.y) - font_metrics.ascent() - highlight_padding,
                                comment.width + highlight_size_extra,
                                comment.height + highlight_size_extra)
            
            # Pixmapを描画 (★★★ 変更点 ★★★)
            shadow = self._scaled_value(self.font_shadow, 0)
            inset = self._comment_pixmap_inset(shadow)
            draw_y = comment.y - font_metrics.ascent() - inset
            painter.drawPixmap(int(comment.x) - inset, int(draw_y), pixmap)

        # リサイズ中はOBS側のキャンバス寸法を合わせやすいよう、
        # 現在のクライアント領域サイズを最前面に表示する。
        if self.resizing:
            painter.save()
            size_text = f"{self.width()} × {self.height()}"
            size_font = QFont(self.font_family)
            size_font.setPixelSize(18)
            size_font.setWeight(QFont.Bold)
            painter.setFont(size_font)

            size_metrics = QFontMetrics(size_font)
            horizontal_padding = 18
            vertical_padding = 10
            badge_width = size_metrics.horizontalAdvance(size_text) + horizontal_padding * 2
            badge_height = size_metrics.height() + vertical_padding * 2
            badge_rect = QRect(
                (self.width() - badge_width) // 2,
                (self.height() - badge_height) // 2,
                badge_width,
                badge_height
            )

            painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
            painter.setBrush(QBrush(QColor(0, 0, 0, 190)))
            painter.drawRoundedRect(badge_rect, 8, 8)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(badge_rect, Qt.AlignCenter, size_text)
            painter.restore()
            
if __name__ == "__main__":
    import time
    
    app = QApplication(sys.argv)
    app.setProperty("comment_time", time.time())
    
    window = CommentOverlayWindow()
    window.show()
    
    test_comments = [
        {"text": "これはテストコメントです"},
        {"text": "透過ウィンドウでコメントが流れます"},
        {"text": "コメント衝突回避アルゴリズムのテスト"},
        {"text": "パフォーマンス最適化されたレンダリング"},
        {"text": "長いコメントもしっかり表示されるかテストします。これは非常に長いコメントです。"},
    ]
    
    def add_test_comment():
        app.setProperty("comment_time", time.time())
        comment = test_comments[len(window.comments) % len(test_comments)]
        window.add_comment(comment)
        if len(window.comments) < 20:
            QTimer.singleShot(1000, add_test_comment)
    
    QTimer.singleShot(1000, add_test_comment)
    
    sys.exit(app.exec_())
