# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: ProtoDecoders/Common.proto
# Protobuf Python Version: 4.25.3
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x1aProtoDecoders/Common.proto\"&\n\x04Time\x12\x0f\n\x07seconds\x18\x01 \x01(\r\x12\r\n\x05nanos\x18\x02 \x01(\r\"Z\n\x0f\x45ncryptedReport\x12\x17\n\x0fpublicKeyRandom\x18\x01 \x01(\x0c\x12\x19\n\x11\x65ncryptedLocation\x18\x02 \x01(\x0c\x12\x13\n\x0bisOwnReport\x18\x03 \x01(\r\"r\n\x19LocationAndRotationOffset\x12)\n\x0f\x65ncryptedReport\x18\x01 \x01(\x0b\x32\x10.EncryptedReport\x12\x18\n\x10\x64\x65viceTimeOffset\x18\x02 \x01(\r\x12\x10\n\x08\x61\x63\x63uracy\x18\x03 \x01(\x02\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'ProtoDecoders.Common_pb2', _globals)
if _descriptor._USE_C_DESCRIPTORS == False:
  DESCRIPTOR._options = None
  _globals['_TIME']._serialized_start=30
  _globals['_TIME']._serialized_end=68
  _globals['_ENCRYPTEDREPORT']._serialized_start=70
  _globals['_ENCRYPTEDREPORT']._serialized_end=160
  _globals['_LOCATIONANDROTATIONOFFSET']._serialized_start=162
  _globals['_LOCATIONANDROTATIONOFFSET']._serialized_end=276
# @@protoc_insertion_point(module_scope)
