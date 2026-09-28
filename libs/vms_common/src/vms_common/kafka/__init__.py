"""Async Kafka producer/consumer wrappers: validate -> handle -> commit, DLQ.

See design_architecture.md §5.1 (conventions) and §15 (reliability).
"""

from vms_common.kafka.consumer import BaseConsumer
from vms_common.kafka.producer import KafkaProducerClient, MessageTooLargeError

__all__ = ["BaseConsumer", "KafkaProducerClient", "MessageTooLargeError"]
